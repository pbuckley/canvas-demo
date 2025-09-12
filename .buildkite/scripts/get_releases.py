#!/usr/bin/env python

# call the Buildkite API to get releases for our services
# build an input step based on the services latest released versions
# which are in fact meta-data on their named pipelines

from urllib.request import Request, urlopen
from os import getenv, popen, system
import json
import datetime
from benedict import benedict
import requests


def create_dynamic_step_key(prefix_fragment):
    '''
    create a dynamic step key so this dynamic pipeline generator
    can be run multiple times in the same pipeline
    we only need to go to the minute, seconds would be overkill?
    '''
    now = datetime.datetime.now()
    return prefix_fragment + '-' + now.strftime("%Y-%m-%d-%H-%M")


def generate_pipeline(pipeline_dict, master_input_dict):
    """
    Generate the dynamic pipeline YAML with all discovered services.
    Now fully dynamic - no hardcoded service limits.
    """
    # Flatten all service fields into one list for the input step
    all_fields = []
    for service_name, service_fields in master_input_dict.items():
        all_fields.extend(service_fields)

    # Set the flattened fields
    pipeline_dict['steps'][0]['fields'] = all_fields

    # Add regions selection at the beginning
    region_step_key = create_dynamic_step_key('region-inputs')
    regions_dict = {
        'select': 'Regions for deploy',
        'key': region_step_key,
        'options': [
            {'label': 'us-east-1', 'value': 'us-east-1'},
            {'label': 'us-east-2', 'value': 'us-east-2'},
            {'label': 'us-west-1', 'value': 'us-west-1'},
            {'label': 'eu-central-1', 'value': 'eu-central-1'},
            {'label': 'eu-west-3', 'value': 'eu-west-3'}
        ],
        'multiple': 'true'
    }

    pipeline_dict['steps'][0]['fields'].insert(0, regions_dict)
    print(f"Generated pipeline with {len(master_input_dict)} services and {len(all_fields)} total fields")
    pipeline_dict.to_yaml(filepath='generated_pipeline.yml')


def fetch_bk_api_token():
    if getenv("BUILDKITE_COMPUTE_TYPE") is not None:
        print("In hosted env, fetching bk api token from secret")
        return str.strip(popen("buildkite-agent secret get readtokenpb").read())
    else:
        print("Running locally, fetching bk api token from env var BK_API_TOKEN")
        return getenv("BK_API_TOKEN")


def get_tagged_pipelines(api_token, org_name, given_tag):
    '''
    Get all pipelines with a given tag, e.g. deployable-svc
    Enhanced with pagination support for organizations with many pipelines
    '''
    print(f"Getting pipelines containing tag: {given_tag}")
    headers = {'Authorization': "Bearer " + api_token}

    # Support pagination - Buildkite API returns 30 items per page by default
    all_pipelines = []
    page = 1
    per_page = 100  # Max allowed per page

    while True:
        params = {'page': page, 'per_page': per_page}
        r = requests.get(
            f"https://api.buildkite.com/v2/organizations/{org_name}/pipelines",
            headers=headers,
            params=params
        )
        r.raise_for_status()  # Raise exception for bad status codes

        pipelines_batch = r.json()
        if not pipelines_batch:  # No more results
            break

        all_pipelines.extend(pipelines_batch)
        print(f"Fetched page {page}: {len(pipelines_batch)} pipelines")

        # If we got fewer than per_page, we're done
        if len(pipelines_batch) < per_page:
            break

        page += 1

    # Filter for pipelines with the specified tag
    filtered_list = [
        pipeline for pipeline in all_pipelines
        if pipeline.get('tags') and given_tag in pipeline['tags']
    ]

    print(f"Found {len(filtered_list)} pipelines with tag '{given_tag}' out of {len(all_pipelines)} total pipelines")
    return filtered_list


def extract_metadata_from_builds(svc_name, builds_json, metadata_extractors):
    """
    Generic metadata extractor that handles all metadata types.
    Uses a dictionary of extractor functions for different metadata types.

    Args:
        svc_name: Service name
        builds_json: List of build data from API
        metadata_extractors: Dict of {metadata_name: (set_to_update, dict_to_update)}

    Returns:
        Dict of extracted metadata organized by type
    """
    results = {}

    for build_details in builds_json:
        metadata = build_details.get('meta_data', {})

        for metadata_key, (data_set, result_dict) in metadata_extractors.items():
            if metadata_key in metadata:
                value = metadata[metadata_key]
                print(f"Found {metadata_key} for {svc_name}: {value}")

                if metadata_key == "rel-ver":
                    data_set.add(value)
                    result_dict[svc_name] = sorted(data_set)
                elif metadata_key == "deploy-hosts":
                    hosts = [host.strip() for host in value.split(",")]
                    data_set.update(hosts)
                    result_dict[svc_name] = sorted(data_set)
                elif metadata_key == "deploy-post-script":
                    data_set.add(value)
                    result_dict[svc_name] = sorted(data_set)

    return metadata_extractors


def get_release_versions(api_token, org_name, deployable_service_pipelines):
    """
    Fetch release metadata for all discovered services.
    Now completely dynamic - handles any number of services.
    """
    # Initialize result dictionaries
    svc_dict = {}
    host_dict = {}
    post_dict = {}

    # Track statistics
    total_services = len(deployable_service_pipelines)
    processed_services = 0

    print(f"Processing {total_services} deployable services...")

    for pipeline_details in deployable_service_pipelines:
        svc_name = pipeline_details['name']
        print(f"\n--- Processing service: {svc_name} ({processed_services + 1}/{total_services}) ---")

        # Get builds for this pipeline
        build_request = Request(pipeline_details['url'] + "/builds")
        build_request.add_header('Authorization', "Bearer " + api_token)

        try:
            svc_builds = urlopen(build_request).read()
            svc_builds_json = json.loads(svc_builds.decode('utf-8'))

            if not svc_builds_json:
                print(f"No builds found for service {svc_name}")
                continue

            print(f"Found {len(svc_builds_json)} builds for {svc_name}")

            # Initialize sets for this service
            svc_versions_set = set()
            svc_hosts_set = set()
            svc_postscript_set = set()

            # Setup metadata extractors
            metadata_extractors = {
                "rel-ver": (svc_versions_set, svc_dict),
                "deploy-hosts": (svc_hosts_set, host_dict),
                "deploy-post-script": (svc_postscript_set, post_dict)
            }

            # Extract metadata from all builds
            extract_metadata_from_builds(svc_name, svc_builds_json, metadata_extractors)

            processed_services += 1

        except Exception as e:
            print(f"Error processing service {svc_name}: {str(e)}")
            continue

    print(f"\n=== Processing Summary ===")
    print(f"Services with versions: {len(svc_dict)}")
    print(f"Services with hosts: {len(host_dict)}")
    print(f"Services with post-scripts: {len(post_dict)}")

    return svc_dict, host_dict, post_dict


def create_service_yaml_fields(service_name, version_dict, host_dict, post_dict):
    """
    Create all YAML fields for a single service.
    Consolidates the three separate translate functions into one.
    """
    fields = []
    keysafe_name = service_name.replace(" ", "-").lower()

    # Version selection field
    if service_name in version_dict:
        version_options = [
            {"label": ver, "value": ver}
            for ver in version_dict[service_name]
        ]
        fields.append({
            "select": f"{service_name} version",
            "key": f"{keysafe_name}-ver",
            "options": version_options
        })

    # Host configuration field
    if service_name in host_dict:
        host_list = ",".join(host_dict[service_name])
        fields.append({
            "text": f"{service_name} host list",
            "key": f"{keysafe_name}-hosts",
            "default": host_list,
            "hint": f"Comma separated list of hosts to deploy {service_name} onto",
            "required": True
        })

    # Post-script field
    if service_name in post_dict:
        post_list = ",".join(post_dict[service_name])
        fields.append({
            "text": f"{service_name} post config script",
            "key": f"{keysafe_name}-pwsh",
            "default": post_list,
            "hint": "Provide filename for optional PS1 to run post deploy.",
            "required": False
        })

    print(f"Created {len(fields)} fields for service: {service_name}")
    return fields


def create_metadata_artifact(deploy_step_key, master_service_dict):
    """
    Create a comprehensive metadata artifact with all discovered services.
    Enhanced to include more useful information for downstream scripts.
    """
    json_filename = create_dynamic_step_key('json-meta-data') + '.json'

    # Create comprehensive metadata
    service_info = {}
    for service_name in master_service_dict.keys():
        keysafe_name = service_name.replace(" ", "-").lower()
        service_info[service_name] = {
            "keysafe_name": keysafe_name,
            "version_key": f"{keysafe_name}-ver",
            "hosts_key": f"{keysafe_name}-hosts",
            "postscript_key": f"{keysafe_name}-pwsh"
        }

    meta_data_dict = {
        "version-prefixes": list(master_service_dict.keys()),
        "most-recent-deploy-step-key": deploy_step_key,
        "service-count": len(master_service_dict),
        "service-info": service_info,
        "generation-timestamp": datetime.datetime.now().isoformat()
    }

    print(f"Creating metadata artifact with {len(master_service_dict)} services")

    with open(json_filename, 'w') as json_file:
        json.dump(meta_data_dict, json_file, indent=4)

    if getenv("BUILDKITE_COMPUTE_TYPE") is not None:
        print(f"In hosted env, uploading artifact {json_filename}")
        artifact_uploaded = str.strip(popen(f"buildkite-agent artifact upload {json_filename}").read())
        print(f"Artifact uploaded: {artifact_uploaded}")
    else:
        print(f"Running locally, would upload artifact: {json_filename}")


def main():
    org_name = "demo"
    given_tag = "deployable-svc"
    api_token = fetch_bk_api_token()

    # Generate dynamic step keys
    input_step_key = create_dynamic_step_key('get-deploy-inputs')
    deploy_step_key = create_dynamic_step_key('gen-deploy-inputs')

    print(f"Using input_step_key: {input_step_key}")
    print(f"Using deploy_step_key: {deploy_step_key}")

    # Create base pipeline structure
    base_pipeline = benedict({
        'steps': [
            {
                'input': 'Provide regions, versions, and targets for :dotnet: deploy',
                'key': input_step_key
            },
            {
                'label': 'Generate deploy targets :slot_machine:',
                'command': '.buildkite/scripts/generate_deploy_targets.py',
                'key': deploy_step_key,
                'depends_on': [input_step_key]
            }
        ],
        'queue': 'q1'
    })

    # Discover all tagged pipelines
    tagged_pipelines = get_tagged_pipelines(api_token, org_name, given_tag)

    if not tagged_pipelines:
        print(f"No pipelines found with tag '{given_tag}'. Exiting.")
        return

    # Extract metadata from all discovered services
    version_dict, host_dict, post_dict = get_release_versions(api_token, org_name, tagged_pipelines)

    if not version_dict:
        print("No release versions found for any services. Check your metadata configuration.")
        return

    print(f"\n=== Final Results ===")
    print(f"Services with versions: {list(version_dict.keys())}")
    print(f"Services with hosts: {list(host_dict.keys())}")
    print(f"Services with post-scripts: {list(post_dict.keys())}")

    # Generate YAML fields for all services dynamically
    master_input_dict = {}
    for service_name in version_dict.keys():
        master_input_dict[service_name] = create_service_yaml_fields(
            service_name, version_dict, host_dict, post_dict
        )

    print(f"\nGenerated input configuration for {len(master_input_dict)} services")

    # Generate the final pipeline
    generate_pipeline(base_pipeline, master_input_dict)

    # Create metadata artifact for downstream consumption
    create_metadata_artifact(deploy_step_key, master_input_dict)

    # Upload pipeline
    if getenv("BUILDKITE_COMPUTE_TYPE") is not None:
        print("In hosted env, uploading pipeline")
        system('buildkite-agent pipeline upload generated_pipeline.yml')
    else:
        print("Running locally, would have run: buildkite-agent pipeline upload generated_pipeline.yml")


if __name__ == "__main__":
    main()
