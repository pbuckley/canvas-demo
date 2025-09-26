#!/usr/bin/env python

# call the Buildkite API to get releases for our services
# build an input step based on the services latest released versions
# which are in fact meta-data on their named pipelines
# Enhanced with caching to avoid duplicate API calls during rollback

from urllib.request import Request, urlopen
from os import getenv, popen, system
import json
import datetime
import argparse
from benedict import benedict
import requests

# Global timestamp for consistent step keys across all dynamic step creation
PIPELINE_TIMESTAMP = datetime.datetime.now().strftime("%Y-%m-%d-%H-%M")


def create_dynamic_step_key(prefix_fragment):
    '''
    create a dynamic step key so this dynamic pipeline generator
    can be run multiple times in the same pipeline
    we only need to go to the minute, seconds would be overkill?
    use PIPELINE_TIMESTAMP so we have one consistent timestamp
    for all steps created by this script
    '''
    return prefix_fragment + '-' + PIPELINE_TIMESTAMP


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


def save_service_cache(version_dict, host_dict, post_dict, tagged_pipelines):
    """
    Save all service metadata to a cache artifact for future rollback scenarios.

    Args:
        version_dict: Service versions dictionary
        host_dict: Service hosts dictionary
        post_dict: Service post-scripts dictionary
        tagged_pipelines: Raw pipeline data from API

    Returns:
        str: Filename of the created cache file
    """
    cache_filename = create_dynamic_step_key('service-cache') + '.json'

    cache_data = {
        "cache_created_at": datetime.datetime.now().isoformat(),
        "cache_version": "1.0",
        "service_metadata": {
            "versions": version_dict,
            "hosts": host_dict,
            "post_scripts": post_dict
        },
        "pipeline_data": {
            pipeline['name']: {
                'slug': pipeline['slug'],
                'url': pipeline['url'],
                'tags': pipeline.get('tags', [])
            }
            for pipeline in tagged_pipelines
        },
        "statistics": {
            "total_services": len(version_dict),
            "services_with_hosts": len(host_dict),
            "services_with_scripts": len(post_dict)
        }
    }

    print(f"💾 Creating service cache with {len(version_dict)} services")

    with open(cache_filename, 'w') as cache_file:
        json.dump(cache_data, cache_file, indent=2, sort_keys=True)

    # Upload the cache artifact
    if getenv("BUILDKITE_COMPUTE_TYPE") is not None:
        print(f"📤 Uploading service cache artifact: {cache_filename}")
        upload_result = str.strip(popen(f"buildkite-agent artifact upload {cache_filename}").read())
        print(f"Cache upload result: {upload_result}")
    else:
        print(f"🔧 Local mode: Would upload cache artifact {cache_filename}")

    return cache_filename


def load_service_cache():
    """
    Load service metadata from previously cached artifact.

    Returns:
        tuple: (version_dict, host_dict, post_dict) or (None, None, None) if cache unavailable
    """
    print("🔍 Looking for existing service cache...")

    if getenv("BUILDKITE_COMPUTE_TYPE") is not None:
        # Download cache artifacts
        download_cmd = 'buildkite-agent artifact download "service-cache*.json" .'
        download_result = str.strip(popen(download_cmd).read())
        print(f"Cache download attempt: {download_result}")

    # Find the most recent cache file
    cache_list_cmd = "ls -1 service-cache*.json 2>/dev/null | sort -r | head -1"
    cache_filename = str.strip(popen(cache_list_cmd).read())

    if not cache_filename:
        print("❌ No service cache found - will need to fetch fresh data")
        return None, None, None

    try:
        print(f"📖 Loading service cache from: {cache_filename}")
        with open(cache_filename, 'r') as cache_file:
            cache_data = json.load(cache_file)

        cache_age = datetime.datetime.fromisoformat(cache_data['cache_created_at'])
        age_minutes = (datetime.datetime.now() - cache_age).total_seconds() / 60

        print(f"✅ Cache loaded successfully (age: {age_minutes:.1f} minutes)")
        print(f"🔢 Cached services: {cache_data['statistics']['total_services']}")

        service_metadata = cache_data['service_metadata']
        return (
            service_metadata['versions'],
            service_metadata['hosts'],
            service_metadata['post_scripts']
        )

    except (IOError, json.JSONDecodeError, KeyError) as e:
        print(f"⚠️ Error loading cache: {e}")
        return None, None, None


def get_tagged_pipelines(api_token, org_name, given_tag):
    '''
    Get all pipelines with a given tag, e.g. deployable-svc
    Enhanced with pagination support for organizations with many pipelines
    '''
    print(f"🔍 Getting pipelines containing tag: {given_tag}")
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
        print(f"📄 Fetched page {page}: {len(pipelines_batch)} pipelines")

        # If we got fewer than per_page, we're done
        if len(pipelines_batch) < per_page:
            break

        page += 1

    # Filter for pipelines with the specified tag
    filtered_list = [
        pipeline for pipeline in all_pipelines
        if pipeline.get('tags') and given_tag in pipeline['tags']
    ]

    print(f"🎯 Found {len(filtered_list)} pipelines with tag '{given_tag}' out of {len(all_pipelines)} total pipelines")
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
                print(f"  📋 Found {metadata_key} for {svc_name}: {value}")

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

    print(f"🚀 Processing {total_services} deployable services...")

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
                print(f"⚠️ No builds found for service {svc_name}")
                continue

            print(f"📦 Found {len(svc_builds_json)} builds for {svc_name}")

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
            print(f"❌ Error processing service {svc_name}: {str(e)}")
            continue

    print(f"\n=== 📊 Processing Summary ===")
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

    print(f"🔧 Created {len(fields)} fields for service: {service_name}")
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

    print(f"📋 Creating metadata artifact with {len(master_service_dict)} services")

    with open(json_filename, 'w') as json_file:
        json.dump(meta_data_dict, json_file, indent=4)

    if getenv("BUILDKITE_COMPUTE_TYPE") is not None:
        print(f"📤 In hosted env, uploading artifact {json_filename}")
        artifact_uploaded = str.strip(popen(f"buildkite-agent artifact upload {json_filename}").read())
        print(f"Artifact uploaded: {artifact_uploaded}")
    else:
        print(f"🔧 Running locally, would upload artifact: {json_filename}")


def parse_args():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description='Generate dynamic Buildkite deployment input steps',
        epilog='''
Examples:
  # Fresh discovery (first run):
  python get_releases.py

  # Rollback mode (uses cached data):
  python get_releases.py --rollback
        ''',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument(
        '--rollback',
        action='store_true',
        help='Use cached service data instead of API discovery (faster rollback mode)'
    )

    return parser.parse_args()


def main():
    args = parse_args()

    org_name = "demo"
    given_tag = "deployable-svc"
    api_token = fetch_bk_api_token()

    # Generate dynamic step keys
    input_step_key = create_dynamic_step_key('get-deploy-inputs')
    deploy_step_key = create_dynamic_step_key('gen-deploy-inputs')

    print(f"🔑 Using input_step_key: {input_step_key}")
    print(f"🔑 Using deploy_step_key: {deploy_step_key}")

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

    if args.rollback:
        print("🔄 ROLLBACK MODE: Attempting to use cached service data...")
        version_dict, host_dict, post_dict = load_service_cache()

        if not version_dict:
            print("⚠️ No cache available - falling back to fresh API discovery")
            args.rollback = False  # Fall through to fresh discovery
        else:
            print(f"🎯 Successfully loaded cache with {len(version_dict)} services")
            print("⚡ Skipping expensive API calls - generating pipeline from cache")

    if not args.rollback:
        print("🔍 FRESH DISCOVERY MODE: Fetching latest service data from API...")

        # Discover all tagged pipelines (expensive API call)
        tagged_pipelines = get_tagged_pipelines(api_token, org_name, given_tag)

        if not tagged_pipelines:
            print(f"❌ No pipelines found with tag '{given_tag}'. Exiting.")
            return

        # Extract metadata from all discovered services (very expensive API calls)
        version_dict, host_dict, post_dict = get_release_versions(api_token, org_name, tagged_pipelines)

        if not version_dict:
            print("❌ No release versions found for any services. Check your metadata configuration.")
            return

        # Save the cache for future rollback scenarios
        cache_filename = save_service_cache(version_dict, host_dict, post_dict, tagged_pipelines)
        print(f"💾 Service cache saved as: {cache_filename}")

    print(f"\n=== 📊 Final Results ===")
    print(f"Services with versions: {list(version_dict.keys())}")
    print(f"Services with hosts: {list(host_dict.keys())}")
    print(f"Services with post-scripts: {list(post_dict.keys())}")

    # Generate YAML fields for all services dynamically
    master_input_dict = {}
    for service_name in version_dict.keys():
        master_input_dict[service_name] = create_service_yaml_fields(
            service_name, version_dict, host_dict, post_dict
        )

    print(f"\n🔧 Generated input configuration for {len(master_input_dict)} services")

    # Generate the final pipeline
    generate_pipeline(base_pipeline, master_input_dict)

    # Create metadata artifact for downstream consumption
    create_metadata_artifact(deploy_step_key, master_input_dict)

    # Upload pipeline
    if getenv("BUILDKITE_COMPUTE_TYPE") is not None:
        print("📤 In hosted env, uploading pipeline")
        upload_result = system('buildkite-agent pipeline upload generated_pipeline.yml')
        if upload_result == 0:
            print("✅ Pipeline uploaded successfully!")
        else:
            print(f"❌ Pipeline upload failed with exit code: {upload_result}")
    else:
        print("🔧 Running locally, would have run: buildkite-agent pipeline upload generated_pipeline.yml")

    # Performance summary
    mode = "ROLLBACK (cached)" if args.rollback else "FRESH DISCOVERY"
    print(f"\n🏁 {mode} mode completed for {len(version_dict)} services")


if __name__ == "__main__":
    main()
