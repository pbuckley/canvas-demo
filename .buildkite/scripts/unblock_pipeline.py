#!/usr/bin/env python3
"""
Simple script to unblock Buildkite pipeline input step.
1. Find the blocked gen-deploy-inputs job
2. Generate new region key with current timestamp
3. Submit the form data

Usage: python unblock_pipeline.py <build_number> <input_data.json>
"""

import sys
import json
import requests
from os import getenv
from datetime import datetime


def fetch_bk_api_token():
    """Get Buildkite API token from environment"""
    token = getenv("BK_API_TOKEN")
    if not token:
        print("Error: BK_API_TOKEN environment variable not set")
        sys.exit(1)
    return token


def create_dynamic_step_key(prefix_fragment):
    """
    Create a dynamic step key with timestamp (matches get_releases.py logic)
    """
    now = datetime.now()
    return prefix_fragment + '-' + now.strftime("%Y-%m-%d-%H-%M")


def get_build_data(org_name, pipeline_slug, build_number, api_token, debug=False):
    """Fetch build data from Buildkite API"""
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
        sys.exit(1)


def find_deploy_inputs_job(build_data):
    """
    Find the blocked input job (manual/waiter type with get-deploy-inputs step key)

    Returns:
        str: Job ID of the blocked input step
    """
    print("\n🔍 Looking for input job (get-deploy-inputs)...")

    for job in build_data.get('jobs', []):
        job_id = job.get('id')
        job_name = job.get('name', 'Unknown')
        job_type = job.get('type')
        job_state = job.get('state')
        step_key = job.get('step_key') or ''

        print(f"📋 Job: {job_name} (type: {job_type}, state: {job_state})")
        print(f"   Step key: {step_key if step_key else 'None'}")
        print(f"   Job ID: {job_id}")

        # Look for the INPUT job: manual/waiter type with get-deploy-inputs step key
        if (step_key and 'get-deploy-inputs' in step_key and
            job_type in ['manual', 'waiter'] and job_state == 'blocked'):
            print(f"🎯 Found blocked input job: {job_id}")
            return job_id

        print()

    print("❌ No blocked input job found")
    print("🤔 We need a manual/waiter job with 'get-deploy-inputs' in the step key")
    return None


def load_input_data(json_file, region_key):
    """
    Load input data from JSON file and add the generated region key

    Args:
        json_file (str): Path to JSON file with service data
        region_key (str): Generated region input key

    Returns:
        dict: Complete form data ready for submission
    """
    try:
        with open(json_file, 'r') as f:
            data = json.load(f)
    except IOError as e:
        print(f"❌ Error reading {json_file}: {e}")
        sys.exit(1)

    # Add the generated region key to the fields
    if 'fields' not in data:
        data['fields'] = {}

    print(f"📝 Generated region key: {region_key}")

    # Add region selection (you can customize these regions)
    data['fields'][region_key] = [
        "us-east-1",
        "us-west-1",
        "eu-central-1"
    ]

    return data


def unblock_job(org_name, pipeline_slug, build_number, job_id, input_data, api_token):
    """
    Submit the unblock request to Buildkite API

    Returns:
        bool: Success status
    """
    url = f"https://api.buildkite.com/v2/organizations/{org_name}/pipelines/{pipeline_slug}/builds/{build_number}/jobs/{job_id}/unblock"
    headers = {
        'Authorization': f'Bearer {api_token}',
        'Content-Type': 'application/json'
    }

    print(f"🚀 Unblocking job: {job_id}")
    print(f"📤 URL: {url}")
    print(f"📝 Submitting data:")
    print(json.dumps(input_data, indent=2))

    try:
        response = requests.put(url, headers=headers, json=input_data)
        response.raise_for_status()

        print("✅ Pipeline unblocked successfully!")
        return True

    except requests.RequestException as e:
        print(f"❌ Error unblocking job: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"HTTP Status: {e.response.status_code}")
            print(f"Response: {e.response.text}")
        return False


def main():
    if len(sys.argv) < 3:
        print("Usage: python unblock_pipeline.py <build_number> <input_data.json> [--debug]")
        print("\nExample:")
        print("  python unblock_pipeline.py 210 deployment_data.json")
        print("  python unblock_pipeline.py 210 deployment_data.json --debug")
        sys.exit(1)

    build_number = sys.argv[1]
    input_file = sys.argv[2]
    debug_mode = "--debug" in sys.argv

    # Configuration
    org_name = "demo"
    pipeline_slug = "demo-pipeline-canvas"  # Set this to your actual pipeline

    print(f"🎯 Unblocking build #{build_number} in {org_name}/{pipeline_slug}")
    if debug_mode:
        print("🐛 Debug mode enabled")

    # Get API token
    api_token = fetch_bk_api_token()

    # Step 1: Get build data
    build_data = get_build_data(org_name, pipeline_slug, build_number, api_token, debug=debug_mode)

    # Step 2: Find the blocked gen-deploy-inputs job
    job_id = find_deploy_inputs_job(build_data)
    if not job_id:
        sys.exit(1)

    # Step 3: Generate new region input key (with current timestamp)
    region_key = create_dynamic_step_key('region-inputs')

    # Step 4: Load input data and add region key
    input_data = load_input_data(input_file, region_key)

    # Step 5: Submit the unblock request
    success = unblock_job(org_name, pipeline_slug, build_number, job_id, input_data, api_token)

    if success:
        print("🎉 Pipeline proceeding with deployment!")
    else:
        print("💥 Failed to unblock pipeline")
        sys.exit(1)


if __name__ == "__main__":
    main()
