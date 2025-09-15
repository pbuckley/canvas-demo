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


def find_region_input_key(build_data):
    """
    Find the dynamic region input key with timestamp pattern.
    Looks for keys matching: region-inputs-YYYY-MM-DD-HH-MM

    Returns:
        str: The region input key, or None if not found
    """
    print("\n🔍 === DEBUGGING BUILD DATA STRUCTURE ===")
    print(f"📋 Build data keys: {list(build_data.keys())}")
    print(f"🏗️  Build state: {build_data.get('state', 'unknown')}")
    print(f"📊 Total jobs: {len(build_data.get('jobs', []))}")

    # Check build-level metadata
    meta_data = build_data.get('meta_data', {})
    print(f"🏷️  Build meta_data keys: {list(meta_data.keys())}")

    if meta_data:
        print("📝 Build meta_data contents:")
        for k, v in meta_data.items():
            print(f"  {k}: {v}")

    # Also check if region data is stored in jobs or steps
    print("\n🔍 Checking jobs for region data...")
    for i, job in enumerate(build_data.get('jobs', [])):
        job_name = job.get('name', f'Job {i}')
        job_type = job.get('type', 'unknown')
        job_state = job.get('state', 'unknown')
        print(f"  Job {i}: {job_name} (type: {job_type}, state: {job_state})")

        # Check job-level metadata
        if 'meta_data' in job:
            job_meta = job.get('meta_data', {})
            if job_meta:
                print(f"    Job meta_data: {job_meta}")

        # Check if this is an input job with fields
        if job_type == 'waiter' and 'fields' in job:
            print(f"    🎯 Input job fields: {list(job.get('fields', {}).keys())}")

    # Check steps array too (sometimes data is here)
    print(f"\n🔍 Checking steps array... (found {len(build_data.get('steps', []))} steps)")
    for i, step in enumerate(build_data.get('steps', [])):
        step_name = step.get('name', f'Step {i}')
        step_type = step.get('type', 'unknown')
        print(f"  Step {i}: {step_name} (type: {step_type})")
        if 'meta_data' in step:
            step_meta = step.get('meta_data', {})
            if step_meta:
                print(f"    Step meta_data: {step_meta}")

    # Pattern matches region-inputs-YYYY-MM-DD-HH-MM (no seconds, per your get_releases.py)
    pattern = r"region-inputs-(\d{4}-\d{2}-\d{2}-\d{2}-\d{2})"

    print(f"\n🔎 Searching for pattern: {pattern}")

    # Search in build metadata
    matching_keys = []
    for key in meta_data.keys():
        print(f"  Testing key: '{key}'")
        match = re.match(pattern, key)
        if match:
            # Extract datetime for sorting (get most recent)
            dt_str = match.group(1)
            dt_obj = datetime.strptime(dt_str, "%Y-%m-%d-%H-%M")
            matching_keys.append((key, dt_obj))
            print(f"    ✅ MATCH! Found region input key: {key}")
        else:
            print(f"    ❌ No match")

    # If not found in build metadata, search in job metadata
    if not matching_keys:
        print("\n🔍 Searching job metadata for region keys...")
        for job in build_data.get('jobs', []):
            job_meta = job.get('meta_data', {})
            for key in job_meta.keys():
                print(f"  Testing job meta key: '{key}'")
                match = re.match(pattern, key)
                if match:
                    dt_str = match.group(1)
                    dt_obj = datetime.strptime(dt_str, "%Y-%m-%d-%H-%M")
                    matching_keys.append((key, dt_obj))
                    print(f"    ✅ MATCH in job! Found region input key: {key}")

    if not matching_keys:
        print("❌ No region input key found anywhere")
        print("🤔 This might mean:")
        print("   1. The input step hasn't been created yet")
        print("   2. The region data is stored differently than expected")
        print("   3. We're looking at the wrong build/pipeline")
        return None

    # Sort by datetime (most recent first) and return the key
    most_recent_key = sorted(matching_keys, key=lambda x: x[1], reverse=True)[0][0]
    print(f"✅ Using most recent region key: {most_recent_key}")
    return most_recent_key


def find_blocked_input_job(build_data):
    """
    Find the blocked input step job ID.

    Returns:
        str: Job ID of the blocked input step
    """
    print("\n🔍 === DEBUGGING JOB SEARCH ===")

    blocked_jobs = []
    input_jobs = []
    all_jobs = []

    for job in build_data.get('jobs', []):
        job_id = job.get('id', 'unknown')
        job_name = job.get('name', 'Unknown')
        job_type = job.get('type', 'unknown')
        job_state = job.get('state', 'unknown')

        all_jobs.append((job_name, job_type, job_state, job_id))

        print(f"🔍 Job: '{job_name}'")
        print(f"   Type: {job_type}, State: {job_state}, ID: {job_id}")

        # Collect input/waiter jobs
        if job_type == 'waiter':
            input_jobs.append((job_name, job_state, job_id))
            print(f"   ⭐ This is a waiter/input job!")

            # Check if it has fields (input form)
            if 'fields' in job:
                fields = job.get('fields', [])
                print(f"   📝 Has {len(fields)} input fields:")
                for field in fields:
                    if isinstance(field, dict):
                        field_key = field.get('key', 'no-key')
                        field_type = field.get('select', field.get('text', 'unknown-type'))
                        print(f"      - {field_key}: {field_type}")

        # Collect blocked jobs
        if job_state == 'blocked':
            blocked_jobs.append((job_name, job_type, job_id))
            print(f"   🚫 This job is BLOCKED!")

        print()  # Blank line for readability

    print(f"📊 Summary:")
    print(f"   Total jobs: {len(all_jobs)}")
    print(f"   Input/waiter jobs: {len(input_jobs)}")
    print(f"   Blocked jobs: {len(blocked_jobs)}")

    # Look for waiter jobs that are blocked
    for job in build_data.get('jobs', []):
        if job.get('type') == 'waiter' and job.get('state') == 'blocked':
            job_id = job.get('id')
            job_name = job.get('name', 'Unknown')
            print(f"🎯 Found blocked input job: {job_name} (ID: {job_id})")
            return job_id

    print("❌ No blocked input job found")
    print("🤔 Available jobs summary:")
    for name, job_type, state, job_id in all_jobs[:5]:  # Show first 5
        print(f"   {name} ({job_type}, {state})")
    if len(all_jobs) > 5:
        print(f"   ... and {len(all_jobs) - 5} more jobs")

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
    region_key = find_region_input_key(build_data)
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
