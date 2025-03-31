#!/usr/bin/env python

# call the Buildkite API to get releases for our services
# build an input step based on the services latest released versions
# which are in fact meta-data on their named pipelines

from urllib.request import Request, urlopen
from os import getenv, popen
import json
from benedict import benedict
import requests


def generate_pipeline(pipeline_dict):
    print("here we generate our pipeline")
    pipeline_dict.to_yaml(filepath='generated_pipeline.yml')


def fetch_bk_api_token():
    if getenv("BUILDKITE_COMPUTE_TYPE") is not None:
        print("In hosted env, fetching bk api token from secret")
        return str.strip(popen("buildkite-agent secret get readtokenpb").read())
    else:
        print("Running locally, fetching bk api token from env var BK_API_TOKEN")
        return getenv("BK_API_TOKEN")


def get_tagged_pipelines(api_token, given_tag):
    '''
    get all pipelines with a given tag, e.g. deployable-svc
    this way, the pipelines do not even need to follow a naming convention
    given_tag: a string with a valid tag
    '''
    print(f"Getting pipelines containing {given_tag}")
    # I want to support pagination but `demo` org only has 30 pipelines, under the default single page limit
    # curl -H "Authorization: Bearer ${BK_API_TOKEN}" -X GET "https://api.buildkite.com/v2/organizations/demo/pipelines"
    headers = {'Authorization': "Bearer " + api_token}
    r = requests.get("https://api.buildkite.com/v2/organizations/demo/pipelines", headers=headers)
    full_dict = r.json()
    filtered_list = [item for item in full_dict if item.get('tags') and 'deployable-svc' in item['tags']]
    return filtered_list


def get_release_versions(api_token, deployable_service_pipelines):

    for pipeline_details in deployable_service_pipelines:
        named_pipeline = pipeline_details['name']
        print(f"Getting builds for {pipeline_details['name']}...")
        build_request = Request(f"https://api.buildkite.com/v2/organizations/demo/pipelines/{named_pipeline}/builds")
        # build_request = Request("https://api.buildkite.com/v2/organizations/demo/pipelines/service-foo/builds")
        build_request.add_header('Authorization', "Bearer " + api_token)

        svc_builds = urlopen(build_request).read()

        svc_builds_json = json.loads(svc_builds.decode('utf-8'))
        print(f"Our whole svc_builds_json {json.dumps(svc_builds_json)}")

        # get one build

        for svc_build in svc_builds_json:
            # what is wrong with this, we are in some inner list here?
            print(f"svc_build is wat?: {svc_build}")
            svc_name = svc_build['pipeline']['name']
            svc_url = svc_build['url']
            print(f"Service of name: {svc_name} has url: {svc_url}")
            one_build_request = Request(svc_build['url']) # https://buildkite.com/docs/apis/rest-api/builds#get-a-build
            one_build_request.add_header('Authorization', "Bearer " + api_token)

            one_build_result = urlopen(build_request).read()

            one_build_json = json.loads(one_build_result.decode('utf-8'))
            # print(json.dumps(one_build_json))
            for meta_data in one_build_json:
                print(meta_data['meta_data']['rel-ver'])


def main():
    api_token = fetch_bk_api_token()
    base_pipeline = benedict({'steps': [{'label': 'pre command', 'command': 'python3 /Users/peter/proj/canvas-demo/.buildkite/scripts/get_releases.py', 'agents': {'queue': 'mccue'}}, {'input': 'Provide versions and targets for :dotnet: deploy', 'key': 'get-deploy-inputs', 'fields': [{'select': 'Service Foo version', 'key': 'svc-foo-ver', 'options': [{'label': '1.33', 'value': '1.33'}, {'label': '1.35', 'value': '1.38'}, {'label': '1.38', 'value': '1.38'}]}, {'text': ':windows: Service Foo Host List', 'key': 'svc-foo-hosts', 'hint': 'Comma separated list of hosts to deploy Service Foo onto', 'required': True, 'default': 'iis_server01,iis_server02,iis_server03'}, {'text': ':pwsh: Service Foo post config script', 'key': 'svc-foo-pwsh', 'hint': 'Provide filename for optional PS1 to run post deploy.', 'required': False, 'default': 'ServiceFooDefault.PS1'}, {'select': 'Service Bar version', 'key': 'svc-bar-ver', 'options': [{'label': '2.54', 'value': '2.54'}, {'label': '2.79', 'value': '2.79'}, {'label': '3.01RC', 'value': '3.01RC'}]}, {'text': ':pwsh: Service Bar post config script', 'key': 'svc-bar-pwsh', 'hint': 'Provide filename for optional PS1 to run post deploy.', 'required': False, 'default': 'ServiceBarDefault.PS1'}, {'text': ':windows: Service Bar Host List', 'key': 'svc-bar-hosts', 'hint': 'Comma separated list of hosts to deploy Service Bar onto', 'required': True, 'default': 'file_server01,file_server02,file_server03'}, {'select': 'Service Web version', 'key': 'svc-web-ver', 'options': [{'label': '7.45', 'value': '7.45'}, {'label': '8.19', 'value': '8.19'}, {'label': '8.04a', 'value': '8.04a'}]}, {'text': ':windows: Service Web Host List', 'key': 'svc-web-hosts', 'hint': 'Comma separated list of hosts to deploy Service Web onto', 'required': True, 'default': 'web_server1103,web_server2984,web_server1849'}, {'text': ':pwsh: Service Web post config script', 'key': 'svc-web-pwsh', 'hint': 'Provide filename for optional PS1 to run post deploy.', 'required': False, 'default': 'ServiceWebDefault.PS1'}]}, {'label': 'Generate deploy targets :slot_machine:', 'command': '.buildkite/scripts/generate_deploy_targets.sh', 'key': 'gen-deploy-inputs', 'depends_on': ['get-deploy-inputs']}], 'queue': 'q1'})

    tagged_pipelines = get_tagged_pipelines(api_token, "deployable-svc")
    print(f"Tagged pipelines: {tagged_pipelines}")
    get_release_versions(api_token, tagged_pipelines)
    generate_pipeline(base_pipeline)
    print("made it to end of main fn")


if __name__ == "__main__":
    main()
