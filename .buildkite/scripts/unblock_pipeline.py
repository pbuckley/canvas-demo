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


def get_build_data(org_name, pipeline_slug, build_number, api_token):
    """
    Fetch build data from Buildkite API to find blocked input step.

    Returns:
        dict: Build data from API
    """
    url = f"https://api.buildkite.com/v2/organizations/{org_name}/pipelines/{pipeline_slug}/builds/{build_number}"
    headers = {'Authorization': f'Bearer {api_token}'}

    print(f"🔍 Fetching build data from: {url}")

    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"❌ Error fetching build data: {e}")
        sys.exit(1)


def find_region_input_key(build_data):
    """
    Find the dynamic region input key with timestamp pattern.
    Looks for keys matching: region-inputs-YYYY-MM-DD-HH-MM

    Returns:
        str: The region input key, or None if not found
    """
    meta_data = build_data.get('meta_data', {})

    # Pattern matches region-inputs-YYYY-MM-DD-HH-MM (no seconds, per your get_releases.py)
    pattern = r"region-inputs-(\d{4}-\d{2}-\d{2}-\d{2}-\d{2})"

    matching_keys = []
    for key in meta_data.keys():
        match = re.match(pattern, key)
        if match:
            # Extract datetime for sorting (get most recent)
            dt_str = match.group(1)
            dt_obj = datetime.strptime(dt_str, "%Y-%m-%d-%H-%M")
            matching_keys.append((key, dt_obj))
            print(f"📅 Found region input key: {key}")

    if not matching_keys:
        print("❌ No region input key found in build metadata")
        print("Available metadata keys:", list(meta_data.keys()))
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
    for job in build_data.get('jobs', []):
        # Look for waiter (input) jobs that are blocked
        if job.get('type') == 'waiter' and job.get('state') == 'blocked':
            job_id = job.get('id')
            job_name = job.get('name', 'Unknown')
            print(f"🔒 Found blocked input job: {job_name} (ID: {job_id})")
            return job_id

    print("❌ No blocked input job found")
    print("Available jobs:", [(j.get('name'), j.get('type'), j.get('state')) for j in build_data.get('jobs', [])])
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
    if len(sys.argv) != 3:
        print("Usage: python unblock_pipeline.py <build_number> <input_template.json>")
        print("\nExample:")
        print("  python unblock_pipeline.py 123 deployment_template.json")
        sys.exit(1)

    build_number = sys.argv[1]
    template_file = sys.argv[2]

    # Configuration (you can make these environment variables too)
    org_name = "demo"
    pipeline_slug = getenv("BUILDKITE_PIPELINE_SLUG", "demo-pipeline-canvas")

    print(f"🎯 Unblocking build #{build_number} in {org_name}/{pipeline_slug}")

    # Get API token
    api_token = fetch_bk_api_token()

    # Fetch build data to discover dynamic keys and job ID
    build_data = get_build_data(org_name, pipeline_slug, build_number, api_token)

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
