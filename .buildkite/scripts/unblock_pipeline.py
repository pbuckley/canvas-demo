#!/usr/bin/env python3
"""
Unblock Buildkite pipeline input step with deployment parameters.
Automatically discovers the dynamic region input key and substitutes it into JSON template.

Usage: python unblock_pipeline.py <build_number> <input_template.json>
"""

import sys
import json
import re
import requests
from os import getenv
from datetime import datetime
from string import Template


def fetch_bk_api_token():
    """Get Buildkite API token from environment"""
    token = getenv("BK_API_TOKEN")
    if not token:
        print("Error: BK_API_TOKEN environment variable not set")
        sys.exit(1)
    return token


def get_build_data(org_name, pipeline_slug, build_number, api_token, debug=False):
    """
    Fetch build data from Buildkite API to find blocked input step.

    Args:
        debug (bool): If True, save raw API response to file for inspection

    Returns:
        dict: Build data from API
    """
    url = f"https://api.buildkite.com/v2/organizations/{org_name}/pipelines/{pipeline_slug}/builds/{build_number}"
    headers = {'Authorization': f'Bearer {api_token}'}

    print(f"🔍 Fetching build data from: {url}")

    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()

        build_data = response.json()

        if debug:
            debug_filename = f"build_{build_number}_debug.json"
            with open(debug_filename, 'w') as f:
                json.dump(build_data, f, indent=2)
            print(f"📁 Raw API response saved to: {debug_filename}")

        return build_data

    except requests.RequestException as e:
        print(f"❌ Error fetching build data: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"   HTTP Status: {e.response.status_code}")
            print(f"   Response: {e.response.text[:500]}...")
        sys.exit(1)


def find_region_input_key_or_predict(build_data, build_number):
    """
    Find the dynamic region input key, or predict what it should be.

    The region key only exists AFTER the input form is submitted, but we need to
    know what key to use BEFORE submitting. So we'll predict it based on the
    input step's creation time or step key.

    Returns:
        str: The region input key (existing or predicted)
    """
    print("\n🔍 === FINDING OR PREDICTING REGION KEY ===")

    # First, check if region key already exists in metadata (from previous submission)
    meta_data = build_data.get('meta_data', {})
    pattern = r"region-inputs-(\d{4}-\d{2}-\d{2}-\d{2}-\d{2})"

    existing_keys = []
    for key in meta_data.keys():
        match = re.match(pattern, key)
        if match:
            existing_keys.append(key)
            print(f"✅ Found existing region key in metadata: {key}")

    if existing_keys:
        # Use most recent existing key
        latest_key = sorted(existing_keys, reverse=True)[0]
        print(f"🎯 Using existing region key: {latest_key}")
        return latest_key

    print("🔮 No existing region key found, need to predict one...")

    # Strategy: Look at the input step's step_key to extract the timestamp
    # From get_releases.py, the pattern is: get-deploy-inputs-YYYY-MM-DD-HH-MM
    # And regions use: region-inputs-YYYY-MM-DD-HH-MM (same timestamp)

    for job in build_data.get('jobs', []):
        if job.get('type') == 'waiter':  # This is our input step
            step_key = job.get('step_key', '')
            job_name = job.get('name', 'Unknown')

            print(f"🎯 Found input step: {job_name}")
            print(f"📋 Step key: {step_key}")

            # Extract timestamp from step key like: get-deploy-inputs-2025-09-15-17-45
            input_pattern = r"get-deploy-inputs-(\d{4}-\d{2}-\d{2}-\d{2}-\d{2})"
            match = re.search(input_pattern, step_key)

            if match:
                timestamp = match.group(1)
                predicted_region_key = f"region-inputs-{timestamp}"
                print(f"🎯 Predicted region key: {predicted_region_key}")
                return predicted_region_key
            else:
                print(f"❌ Could not extract timestamp from step key: {step_key}")

    # Fallback: Try to predict based on job creation time
    print("🔮 Trying fallback: predict from input job creation time...")

    for job in build_data.get('jobs', []):
        if job.get('type') == 'waiter':
            created_at = job.get('created_at', '')
            if created_at:
                # Parse ISO timestamp: 2025-09-15T17:45:13.050Z
                try:
                    from datetime import datetime
                    dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                    # Round down to nearest minute (as get_releases.py does)
                    rounded_dt = dt.replace(second=0, microsecond=0)
                    timestamp = rounded_dt.strftime("%Y-%m-%d-%H-%M")
                    predicted_key = f"region-inputs-{timestamp}"
                    print(f"🎯 Predicted region key from creation time: {predicted_key}")
                    return predicted_key
                except Exception as e:
                    print(f"❌ Error parsing creation time {created_at}: {e}")

    print("❌ Could not find or predict region input key")
    return None


def find_blocked_input_job(build_data):
    """
    Find the blocked input step job ID.

    Returns:
        str: Job ID of the blocked input step
    """
    print("\n🔍 === FINDING BLOCKED INPUT JOB ===")

    for job in build_data.get('jobs', []):
        job_id = job.get('id', 'unknown')
        job_name = job.get('name', 'Unknown')
        job_type = job.get('type', 'unknown')
        job_state = job.get('state', 'unknown')
        step_key = job.get('step_key', '')

        print(f"🔍 Job: '{job_name}' (type: {job_type}, state: {job_state})")
        if step_key:
            print(f"   Step key: {step_key}")

        # Look for manual/waiter jobs that are blocked
        # From your debug output: Job 2: Job 2 (type: manual, state: blocked)
        if job_type in ['waiter', 'manual'] and job_state == 'blocked':
            # Double-check this is an input step by looking for input-related step keys
            if 'input' in step_key.lower() or 'deploy-inputs' in step_key.lower():
                print(f"🎯 Found blocked input job: {job_name} (ID: {job_id})")
                return job_id
            else:
                print(f"⚠️  Blocked {job_type} job but doesn't look like input step: {step_key}")

    # Fallback: any blocked manual/waiter job
    for job in build_data.get('jobs', []):
        if job.get('type') in ['waiter', 'manual'] and job.get('state') == 'blocked':
            job_id = job.get('id')
            job_name = job.get('name', 'Unknown')
            print(f"🎯 Fallback: Using blocked {job.get('type')} job: {job_name} (ID: {job_id})")
            return job_id

    print("❌ No blocked input job found")
    return None


def load_and_substitute_template(template_file, region_key):
    """
    Load JSON template and substitute the REGION_INPUTS placeholder.

    Args:
        template_file (str): Path to JSON template file
        region_key (str): The discovered region input key

    Returns:
        dict: Substituted JSON data ready for API call
    """
    try:
        with open(template_file, 'r') as f:
            template_content = f.read()
    except IOError as e:
        print(f"❌ Error reading template file {template_file}: {e}")
        sys.exit(1)

    # Use Python's Template class for safe substitution
    template = Template(template_content)

    try:
        substituted_content = template.substitute(REGION_INPUTS=region_key)
        return json.loads(substituted_content)
    except (KeyError, json.JSONDecodeError) as e:
        print(f"❌ Error processing template: {e}")
        print("Make sure your JSON template uses $REGION_INPUTS as a placeholder")
        sys.exit(1)


def unblock_pipeline(org_name, pipeline_slug, build_number, job_id, input_data, api_token):
    """
    Send unblock request to Buildkite API.

    Args:
        org_name (str): Buildkite organization name
        pipeline_slug (str): Pipeline slug
        build_number (str): Build number
        job_id (str): Job ID to unblock
        input_data (dict): Form data to submit
        api_token (str): API token

    Returns:
        bool: Success status
    """
    url = f"https://api.buildkite.com/v2/organizations/{org_name}/pipelines/{pipeline_slug}/builds/{build_number}/jobs/{job_id}/unblock"
    headers = {
        'Authorization': f'Bearer {api_token}',
        'Content-Type': 'application/json'
    }

    print(f"🚀 Unblocking job at: {url}")
    print(f"📝 Submitting data: {json.dumps(input_data, indent=2)}")

    try:
        response = requests.put(url, headers=headers, json=input_data)
        response.raise_for_status()

        print("✅ Pipeline unblocked successfully!")
        return True

    except requests.RequestException as e:
        print(f"❌ Error unblocking pipeline: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"Response status: {e.response.status_code}")
            print(f"Response body: {e.response.text}")
        return False


def main():
    if len(sys.argv) < 3:
        print("Usage: python unblock_pipeline.py <build_number> <input_template.json> [--debug]")
        print("\nExample:")
        print("  python unblock_pipeline.py 123 deployment_template.json")
        print("  python unblock_pipeline.py 123 deployment_template.json --debug")
        sys.exit(1)

    build_number = sys.argv[1]
    template_file = sys.argv[2]
    debug_mode = "--debug" in sys.argv

    # Configuration (you can make these environment variables too)
    org_name = "demo"
    pipeline_slug = getenv("BUILDKITE_PIPELINE_SLUG", "demo-pipeline-canvas")

    print(f"🎯 Unblocking build #{build_number} in {org_name}/{pipeline_slug}")
    if debug_mode:
        print("🐛 Debug mode enabled - will save raw API response")

    # Get API token
    api_token = fetch_bk_api_token()

    # Fetch build data to discover dynamic keys and job ID
    build_data = get_build_data(org_name, pipeline_slug, build_number, api_token, debug=debug_mode)

    # Find the region input key with timestamp
    region_key = find_region_input_key_or_predict(build_data, build_number)
    if not region_key:
        sys.exit(1)

    # Find the blocked input job
    job_id = find_blocked_input_job(build_data)
    if not job_id:
        sys.exit(1)

    # Load template and substitute the region key
    input_data = load_and_substitute_template(template_file, region_key)

    # Unblock the pipeline
    success = unblock_pipeline(org_name, pipeline_slug, build_number, job_id, input_data, api_token)

    if success:
        print("🎉 Deployment pipeline unblocked and proceeding!")
        sys.exit(0)
    else:
        print("💥 Failed to unblock pipeline")
        sys.exit(1)


if __name__ == "__main__":
    main()
