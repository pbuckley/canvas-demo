#!/usr/bin/env python

from os import getenv, popen, system
from datetime import datetime
from benedict import benedict
import requests
import re


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


def main():
    if getenv("BUILDKITE_COMPUTE_TYPE") is not None:
        print("In hosted env, getting dynamic meta-data")
        # ver is scalar
        svc_foo_ver = str.strip(popen("buildkite-agent meta-data get foo-app-ver").read())
        svc_bar_ver = str.strip(popen("buildkite-agent meta-data get bar-service-ver").read())
        svc_web_ver = str.strip(popen("buildkite-agent meta-data get service-web-ver").read())

        # hosts is csv
        svc_foo_hosts = str.strip(popen("buildkite-agent meta-data get foo-app-hosts").read()).split(",")
        svc_bar_hosts = str.strip(popen("buildkite-agent meta-data get bar-service-hosts").read()).split(",")
        svc_web_hosts = str.strip(popen("buildkite-agent meta-data get service-web-hosts").read()).split(",")

        # scripts is csv, too? but I don't like that it is :(
        svc_foo_pwsh = str.strip(popen("buildkite-agent meta-data get foo-app-pwsh").read()).split(",")
        svc_bar_pwsh = str.strip(popen("buildkite-agent meta-data get bar-service-pwsh").read()).split(",")
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

    foo_step_key = create_dynamic_step_key('foo-deploys')
    bar_step_key = create_dynamic_step_key('bar-deploys')
    web_step_key = create_dynamic_step_key('web-deploys')

    rollback_block_key = create_dynamic_step_key('rollback-block')
    rollback_redeploy_key = create_dynamic_step_key('rollback-redeploy-dynamic')

    rollback_snippet = [{'block': "Rollback / Redeploy ?", 'key': rollback_block_key}, {'label': ':rewind: Rollback / Redeploy', 'key': rollback_redeploy_key, 'command': 'python .buildkite/scripts/get_releases.py', 'depends_on': [rollback_block_key]}]

    # is this even needed for debugging anymore?
    print("All svc vars")
    print(f"svc_foo_ver: {svc_foo_ver}")
    print(f"svc_bar_ver: {svc_bar_ver}")
    print(f"svc_web_ver: {svc_web_ver}")
    print(f"svc_foo_hosts: {svc_foo_hosts}")
    print(f"svc_bar_hosts: {svc_bar_hosts}")
    print(f"svc_web_hosts: {svc_web_hosts}")
    print(f"svc_foo_pwsh: {svc_foo_pwsh}")
    print(f"svc_bar_pwsh: {svc_bar_pwsh}")
    print(f"svc_web_pwsh: {svc_web_pwsh}")

    # region would replace these, it would be the top level group (no nesting of groups?)
    # when we get the build_url, we have meta_data, and that has regions meta-data like so (\n separated):
    # region-inputs-2025-04-09-21-19":"eu-central-1\neu-west-3"},
    # I'm assuming we'll fuzzy match on the metadata because the dtstmp is changing
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

    full_pipeline = benedict({'steps': prefix_list + rollback_snippet, 'queue': 'q1'})

    full_pipeline.to_yaml(filepath='newly_genned_pipeline.yml')

    if getenv("BUILDKITE_COMPUTE_TYPE") is not None:
        print("In hosted env, uploading pipeline")
        system('buildkite-agent pipeline upload newly_genned_pipeline.yml')
    else:
        print("Running locally, would have run: buildkite-agent pipeline upload newly_genned_pipeline.yml")


if __name__ == "__main__":
    main()
