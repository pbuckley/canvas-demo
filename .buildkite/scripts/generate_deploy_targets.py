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
    # Pattern to match keys with the format region-inputs-YYYY-MM-DD-HH-MM (no seconds!!!)
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
    org_name = getenv("BUILDKITE_ORGANIZATION_SLUG")
    pipeline_name = getenv("BUILDKITE_PIPELINE_SLUG")
    build_number = getenv("BUILDKITE_BUILD_NUMBER")
    constructed_url = f"https://api.buildkite.com/v2/organizations/{org_name}/pipelines/{pipeline_name}/builds/{build_number}"
    api_token = fetch_bk_api_token()
    headers = {'Authorization': "Bearer " + api_token}
    print(f"Getting regions from meta_data in {constructed_url}")
    r = requests.get(constructed_url, headers=headers)
    full_build = r.json()
    # filter to just metadata, and then fuzzy match our region metadata like starts with
    print(f"Full build meta_data is: {full_build['meta_data']}")
    # this is hardcoded [0] right now, might have to sort to the most recent later
    # regions_string = [key for key in full_build['meta_data'].keys() if key.startswith("region-inputs-")][0]
    regions_string = get_most_recent_region_key(full_build['meta_data'])
    print(f"We found regions_string {regions_string}")
    return full_build['meta_data'][regions_string].split('\n')


def create_service_list(svc_name, svc_ver, svc_hosts, svc_pwsh):
    full_hosts_list = []
    for svc_host in svc_hosts:
        full_hosts_list.insert(0, {'label': f':windows: Deploy {svc_name} {svc_ver} to {svc_host}', 'command': '.buildkite/scripts/run_mock_deploy.sh', 'retry': {'automatic': [{'exit_status': '*', 'limit': '10'}]}})
        full_hosts_list.insert(1, {'label': f':pwsh: Run {svc_pwsh} for {svc_name} on {svc_host}', 'command': f'echo Running {svc_pwsh} on {svc_host}...'})
    return full_hosts_list


def get_metadata_artifact():
    # org_name = getenv("BUILDKITE_ORGANIZATION_SLUG")
    # pipeline_name = getenv("BUILDKITE_PIPELINE_SLUG")
    build_number = getenv("BUILDKITE_BUILD_NUMBER")
    # constructed_url = f"https://api.buildkite.com/v2/organizations/{org_name}/pipelines/{pipeline_name}/builds/{build_number}"
    # api_token = fetch_bk_api_token()
    # headers = {'Authorization': "Bearer " + api_token}
    # print(f"Getting regions from meta_data in {constructed_url}")
    # r = requests.get(constructed_url, headers=headers)
    # full_build = r.json()
    # # filter to just metadata, and then fuzzy match our region metadata like starts with
    # print(f"Full build meta_data is: {full_build['meta_data']}")

    if getenv("BUILDKITE_COMPUTE_TYPE") is not None:
        print("In hosted env, downloading meta-data artifact")
        # but even with all this, I can just download my artifact from this build, amirite? no need for the api here in this fn?
        # and maybe easier I can use the step ID, do I know that? Or am I stuck sorting for the latest artifact
        # from most recent generated input step?
        print(f"buildkite-agent artifact download \"json-meta-data*.json\" .")
        artifact_downloaded = str.strip(popen(f"buildkite-agent artifact download \"json-meta-data*.json\" .").read())
        print(f"This is the artifact download output: {artifact_downloaded}")
        # let's do the single case of the artifact now and sort to the most recent, later
        # but maybe if I just ls *.json locally with a sort the cream will rise to the top?

    json_filename = str.strip(popen(f"ls -1 json-meta-data-*.json | sort -r | head -1").read())
    meta_data_json = {}
    with open(json_filename, 'r') as json_file:
        meta_data_json = json.load(json_file)
    return meta_data_json['most-recent-deploy-step-key']


def main():
    # so if we had get_releases.py create an artifact that contained the prefixes
    # of foo-app and bar-service and service-web (and the new 4th service we discover)
    # then we could fetch it and generate all of these _ver vars?
    # um... dummy... can I depend on something from earlier in the pipeline generation not this iteration?
    most_recent_deploy_step_key = get_metadata_artifact()
    # if we put it into our artifact, as json, this can be the key from the most recently generated
    # artifact created by get_releases.py, along with our metadata of the prefixes involved in the input step

    if getenv("BUILDKITE_COMPUTE_TYPE") is not None:
        print("In hosted env, getting dynamic meta-data")
        # ver is scalar
        svc_foo_ver = str.strip(popen("buildkite-agent meta-data get app-foo-ver").read())
        svc_bar_ver = str.strip(popen("buildkite-agent meta-data get service-bar-ver").read())
        svc_web_ver = str.strip(popen("buildkite-agent meta-data get service-web-ver").read())

        # hosts is csv
        svc_foo_hosts = str.strip(popen("buildkite-agent meta-data get app-foo-hosts").read()).split(",")
        svc_bar_hosts = str.strip(popen("buildkite-agent meta-data get service-bar-hosts").read()).split(",")
        svc_web_hosts = str.strip(popen("buildkite-agent meta-data get service-web-hosts").read()).split(",")

        # scripts is csv, too? but I don't like that it is :(
        svc_foo_pwsh = str.strip(popen("buildkite-agent meta-data get app-foo-pwsh").read()).split(",")
        svc_bar_pwsh = str.strip(popen("buildkite-agent meta-data get service-bar-pwsh").read()).split(",")
        svc_web_pwsh = str.strip(popen("buildkite-agent meta-data get service-web-pwsh").read()).split(",")
    else:
        # ver is scalar
        svc_foo_ver = '1.234'
        svc_bar_ver = '4.56'
        svc_web_ver = '7.89a'

        # hosts is csv
        svc_foo_hosts = 'appsrv01,appsrv02,appsrv03'.split(",")
        svc_bar_hosts = 'filesrv06,filesrv18'.split(",")
        svc_web_hosts = 'websrv10,websrv13,websrv15'.split(",")

        # scripts is csv, too? but I don't like that it is :(
        svc_foo_pwsh = 'FooAppScript.PS1'
        svc_bar_pwsh = 'BarPostDeploy.sh'
        svc_web_pwsh = 'webconfig.py'

    rollback_block_key = create_dynamic_step_key('rollback-block')
    rollback_redeploy_key = create_dynamic_step_key('rollback-redeploy-dynamic')
    summary_block_key = create_dynamic_step_key('summary-block')

    # this dependency is wonky, I might actually want a block step prior to it so I can trigger manually
    # and then to make this more dynamic so it can pick the latest/most-recent/most-successful deploy
    # or all of them and summarize it in to beautiful markdown
    deploy_summary_key = create_dynamic_step_key('deploy-summary')
    annotation_snippet = [{'block': "Generate Deploy Summary?", 'key': summary_block_key, 'depends_on': [most_recent_deploy_step_key]}, {'label': ':spiral_note_pad: Generate Deploy Summary', 'key': deploy_summary_key, 'command': 'python .buildkite/scripts/generate_annotation_summary.py', 'depends_on': [summary_block_key]}]

    rollback_snippet = [{'block': "Rollback / Redeploy ?", 'key': rollback_block_key}, {'label': ':rewind: Rollback / Redeploy', 'key': rollback_redeploy_key, 'command': 'python .buildkite/scripts/get_releases.py', 'depends_on': [rollback_block_key]}]

    deploy_regions = get_deploy_regions()

    print(f"Deploy regions: {deploy_regions}")

    prefix_list = []
    for region in deploy_regions:
        region_step_key = create_dynamic_step_key(region + '-step-')
        # we are operating in this for block going forward for all logic
        prefix_list.append({'group': f':rocket: :windows: Region {region} Parallel Deploys', 'key': region_step_key, 'steps': []})

    full_foo_hosts = create_service_list("Foo App", svc_foo_ver, svc_foo_hosts, svc_foo_pwsh)
    full_bar_hosts = create_service_list("Service Bar", svc_bar_ver, svc_bar_hosts, svc_bar_pwsh)
    full_web_hosts = create_service_list("Service Web", svc_web_ver, svc_web_hosts, svc_web_pwsh)

    print(f"prefix_list is {prefix_list}")
    print(f"full_foo_hosts is {full_foo_hosts}")

    for prefix in prefix_list:
        prefix['steps'] = full_foo_hosts + full_bar_hosts + full_web_hosts

    full_pipeline = benedict({'steps': prefix_list + annotation_snippet + rollback_snippet, 'queue': 'q1'})

    full_pipeline.to_yaml(filepath='newly_genned_pipeline.yml')

    if getenv("BUILDKITE_COMPUTE_TYPE") is not None:
        print("In hosted env, uploading pipeline")
        system('buildkite-agent pipeline upload newly_genned_pipeline.yml')
    else:
        print("Running locally, would have run: buildkite-agent pipeline upload newly_genned_pipeline.yml")


if __name__ == "__main__":
    main()
