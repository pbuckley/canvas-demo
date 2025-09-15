#!/usr/bin/env python

from os import getenv, popen, system
from datetime import datetime
from benedict import benedict
import requests
import re
import json


def fetch_bk_api_token():
    if getenv("BUILDKITE_COMPUTE_TYPE") is not None:
        print("In hosted env, fetching bk api token from secret")
        return str.strip(popen("buildkite-agent secret get readtokenpb").read())
    else:
        print("Running locally, fetching bk api token from env var BK_API_TOKEN")
        return getenv("BK_API_TOKEN")


def create_dynamic_step_key(prefix_fragment):
    '''
    create a dynamic step key so this dynamic pipeline generator
    can be run multiple times in the same pipeline
    we only need to go to the minute, seconds would be overkill?
    '''
    now = datetime.now()
    return prefix_fragment + '-' + now.strftime("%Y-%m-%d-%H-%M")


def get_most_recent_region_key(meta_data_dict):
    """Pattern to match keys with the format region-inputs-YYYY-MM-DD-HH-MM (no seconds!!!)"""
    pattern = r"region-inputs-(\d{4}-\d{2}-\d{2}-\d{2}-\d{2})"

    matching_keys = []
    for key in meta_data_dict.keys():
        match = re.match(pattern, key)
        if match:
            # Extract the datetime part
            dt_str = match.group(1)
            # Parse the datetime string
            dt_obj = datetime.strptime(dt_str, "%Y-%m-%d-%H-%M")
            matching_keys.append((key, dt_obj))

    # Sort by datetime object (descending) and get the first key
    if matching_keys:
        return sorted(matching_keys, key=lambda x: x[1], reverse=True)[0][0]
    return None


def get_deploy_regions():
    """Fetch the selected deployment regions from build metadata"""
    org_name = getenv("BUILDKITE_ORGANIZATION_SLUG")
    pipeline_name = getenv("BUILDKITE_PIPELINE_SLUG")
    build_number = getenv("BUILDKITE_BUILD_NUMBER")
    constructed_url = f"https://api.buildkite.com/v2/organizations/{org_name}/pipelines/{pipeline_name}/builds/{build_number}"
    api_token = fetch_bk_api_token()
    headers = {'Authorization': "Bearer " + api_token}

    print(f"Getting regions from meta_data in {constructed_url}")
    r = requests.get(constructed_url, headers=headers)
    r.raise_for_status()

    full_build = r.json()
    print(f"Full build meta_data keys: {list(full_build['meta_data'].keys())}")

    regions_string = get_most_recent_region_key(full_build['meta_data'])
    if not regions_string:
        print("No region metadata found!")
        return []

    print(f"Found regions_string: {regions_string}")
    return full_build['meta_data'][regions_string].split('\n')


def get_metadata_artifact():
    """
    Download and parse the metadata artifact created by get_releases.py
    Returns the most recent deploy step key for dependency tracking
    """
    if getenv("BUILDKITE_COMPUTE_TYPE") is not None:
        print("In hosted env, downloading meta-data artifact")
        artifact_pattern = "json-meta-data*.json"
        download_cmd = f'buildkite-agent artifact download "{artifact_pattern}" .'
        print(f"Running: {download_cmd}")
        artifact_downloaded = str.strip(popen(download_cmd).read())
        print(f"Artifact download output: {artifact_downloaded}")
    else:
        print("Running locally, assuming metadata artifact exists")

    # Get the most recent artifact file
    json_filename = str.strip(popen("ls -1 json-meta-data-*.json | sort -r | head -1").read())

    if not json_filename:
        print("ERROR: No metadata artifact found!")
        return None

    print(f"Using metadata file: {json_filename}")

    with open(json_filename, 'r') as json_file:
        meta_data_json = json.load(json_file)

    print(f"Loaded metadata for {meta_data_json.get('service-count', 0)} services")
    return meta_data_json


def get_service_metadata_dynamically(service_info):
    """
    Dynamically fetch metadata for all services using the service info from the artifact.
    Replaces the hardcoded service variable fetching.

    Args:
        service_info: Dictionary of service information from metadata artifact

    Returns:
        Dictionary containing all service metadata organized by service name
    """
    all_service_data = {}

    for service_name, service_config in service_info.items():
        keysafe_name = service_config['keysafe_name']

        service_data = {
            'name': service_name,
            'keysafe_name': keysafe_name
        }

        if getenv("BUILDKITE_COMPUTE_TYPE") is not None:
            print(f"Fetching metadata for service: {service_name}")

            # Get version (scalar)
            version_cmd = f"buildkite-agent meta-data get {service_config['version_key']}"
            service_data['version'] = str.strip(popen(version_cmd).read())

            # Get hosts (CSV)
            hosts_cmd = f"buildkite-agent meta-data get {service_config['hosts_key']}"
            hosts_raw = str.strip(popen(hosts_cmd).read())
            service_data['hosts'] = hosts_raw.split(",") if hosts_raw else []

            # Get post-scripts (CSV - though ideally this should be a single value)
            pwsh_cmd = f"buildkite-agent meta-data get {service_config['postscript_key']}"
            pwsh_raw = str.strip(popen(pwsh_cmd).read())
            service_data['postscripts'] = pwsh_raw.split(",") if pwsh_raw else []

        else:
            # Local testing data - generate reasonable defaults
            print(f"Using local test data for service: {service_name}")
            service_data['version'] = f"{len(service_name)}.{hash(service_name) % 100}"
            service_data['hosts'] = [f"{keysafe_name}srv{i:02d}" for i in range(1, 4)]
            service_data['postscripts'] = [f"{keysafe_name}_post_deploy.ps1"]

        all_service_data[service_name] = service_data

        print(f"Service {service_name}: v{service_data['version']}, "
              f"{len(service_data['hosts'])} hosts, "
              f"{len(service_data['postscripts'])} scripts")

    return all_service_data


def create_service_deploy_steps(service_data):
    """
    Create deployment steps for a single service.
    Replaces the hardcoded create_service_list function.

    Args:
        service_data: Dictionary containing service metadata

    Returns:
        List of deployment step dictionaries
    """
    service_name = service_data['name']
    service_version = service_data['version']
    service_hosts = service_data['hosts']
    service_scripts = service_data['postscripts']

    deploy_steps = []

    for host in service_hosts:
        # Main deployment step
        deploy_steps.append({
            'label': f':windows: Deploy {service_name} {service_version} to {host}',
            'command': '.buildkite/scripts/run_mock_deploy.sh',
            'retry': {
                'automatic': [{'exit_status': '*', 'limit': '10'}]
            }
        })

        # Post-deployment script step (if scripts exist)
        if service_scripts and service_scripts[0]:  # Check if there's actually a script
            script_name = service_scripts[0]  # Use first script for now
            deploy_steps.append({
                'label': f':gear: Run {script_name} for {service_name} on {host}',
                'command': f'echo Running {script_name} on {host}...'
            })

    return deploy_steps


def main():
    print("=== Starting Dynamic Deploy Target Generation ===")

    # Load metadata artifact to get service information
    metadata = get_metadata_artifact()
    if not metadata:
        print("ERROR: Cannot proceed without metadata artifact")
        return

    most_recent_deploy_step_key = metadata['most-recent-deploy-step-key']
    service_info = metadata['service-info']

    print(f"Processing {len(service_info)} services...")

    # Dynamically fetch all service metadata
    all_service_data = get_service_metadata_dynamically(service_info)

    if not all_service_data:
        print("ERROR: No service data retrieved")
        return

    # Get deployment regions
    deploy_regions = get_deploy_regions()
    if not deploy_regions:
        print("ERROR: No deployment regions specified")
        return

    print(f"Deploying to regions: {deploy_regions}")

    # Create dynamic step keys
    rollback_block_key = create_dynamic_step_key('rollback-block')
    rollback_redeploy_key = create_dynamic_step_key('rollback-redeploy-dynamic')
    deploy_summary_key = create_dynamic_step_key('deploy-summary')

    # Create region groups
    region_groups = []
    for region in deploy_regions:
        region_step_key = create_dynamic_step_key(f'{region}-step')

        # Collect all deployment steps for all services in this region
        all_deploy_steps = []
        for service_name, service_data in all_service_data.items():
            service_steps = create_service_deploy_steps(service_data)
            all_deploy_steps.extend(service_steps)

        region_groups.append({
            'group': f':rocket: :earth_americas: Region {region} Parallel Deploys',
            'key': region_step_key,
            'steps': all_deploy_steps
        })

    # Create post-deployment steps
    annotation_snippet = [{
        'label': ':spiral_note_pad: Generate Deploy Summary',
        'key': deploy_summary_key,
        'command': 'python .buildkite/scripts/generate_annotation_summary.py',
        'priority': 10,
        'depends_on': [most_recent_deploy_step_key]
    }]

    rollback_snippet = [
        {
            'block': "Rollback / Redeploy ?",
            'key': rollback_block_key
        },
        {
            'label': ':rewind: Rollback / Redeploy',
            'key': rollback_redeploy_key,
            'command': 'python .buildkite/scripts/get_releases.py',
            'depends_on': [rollback_block_key]
        }
    ]

    # Debug output
    print("\n=== Service Configuration Summary ===")
    for service_name, service_data in all_service_data.items():
        print(f"{service_name}: v{service_data['version']}")
        print(f"  Hosts: {', '.join(service_data['hosts'])}")
        print(f"  Scripts: {', '.join(service_data['postscripts'])}")

    print(f"\n=== Pipeline Structure ===")
    print(f"Region groups: {len(region_groups)}")
    total_steps = sum(len(group['steps']) for group in region_groups)
    print(f"Total deployment steps: {total_steps}")

    # Assemble full pipeline
    full_pipeline = benedict({
        'steps': region_groups + annotation_snippet + rollback_snippet,
        'queue': 'q1'
    })

    # Generate pipeline file
    full_pipeline.to_yaml(filepath='newly_genned_pipeline.yml')

    # Upload pipeline
    if getenv("BUILDKITE_COMPUTE_TYPE") is not None:
        print("In hosted env, uploading pipeline")
        result = system('buildkite-agent pipeline upload newly_genned_pipeline.yml')
        if result == 0:
            print("Pipeline uploaded successfully!")
        else:
            print(f"Pipeline upload failed with exit code: {result}")
    else:
        print("Running locally, would have run: buildkite-agent pipeline upload newly_genned_pipeline.yml")
        print("Generated pipeline file: newly_genned_pipeline.yml")


if __name__ == "__main__":
    main()
