#!/usr/bin/env python

# call the Buildkite API to get releases for our services
# build an input step based on the services latest released versions
# which are in fact meta-data on their named pipelines

#import requests # maybe switch to this, making it avail on the custom hosted agent image
import subprocess
# import urllib.request
from urllib.request import Request, urlopen
from os import environ
import json
from benedict import benedict


def generate_pipeline():
    base_pipeline = benedict({'steps': [{'label': 'pre command', 'command': 'python3 /Users/peter/proj/canvas-demo/.buildkite/scripts/get_releases.py', 'agents': {'queue': 'mccue'}}, {'input': 'Provide versions and targets for :dotnet: deploy', 'key': 'get-deploy-inputs', 'fields': [{'select': 'Service Foo version', 'key': 'svc-foo-ver', 'options': [{'label': '1.33', 'value': '1.33'}, {'label': '1.35', 'value': '1.38'}, {'label': '1.38', 'value': '1.38'}]}, {'text': ':windows: Service Foo Host List', 'key': 'svc-foo-hosts', 'hint': 'Comma separated list of hosts to deploy Service Foo onto', 'required': True, 'default': 'iis_server01,iis_server02,iis_server03'}, {'text': ':pwsh: Service Foo post config script', 'key': 'svc-foo-pwsh', 'hint': 'Provide filename for optional PS1 to run post deploy.', 'required': False, 'default': 'ServiceFooDefault.PS1'}, {'select': 'Service Bar version', 'key': 'svc-bar-ver', 'options': [{'label': '2.54', 'value': '2.54'}, {'label': '2.79', 'value': '2.79'}, {'label': '3.01RC', 'value': '3.01RC'}]}, {'text': ':pwsh: Service Bar post config script', 'key': 'svc-bar-pwsh', 'hint': 'Provide filename for optional PS1 to run post deploy.', 'required': False, 'default': 'ServiceBarDefault.PS1'}, {'text': ':windows: Service Bar Host List', 'key': 'svc-bar-hosts', 'hint': 'Comma separated list of hosts to deploy Service Bar onto', 'required': True, 'default': 'file_server01,file_server02,file_server03'}, {'select': 'Service Web version', 'key': 'svc-web-ver', 'options': [{'label': '7.45', 'value': '7.45'}, {'label': '8.19', 'value': '8.19'}, {'label': '8.04a', 'value': '8.04a'}]}, {'text': ':windows: Service Web Host List', 'key': 'svc-web-hosts', 'hint': 'Comma separated list of hosts to deploy Service Web onto', 'required': True, 'default': 'web_server1103,web_server2984,web_server1849'}, {'text': ':pwsh: Service Web post config script', 'key': 'svc-web-pwsh', 'hint': 'Provide filename for optional PS1 to run post deploy.', 'required': False, 'default': 'ServiceWebDefault.PS1'}]}, {'label': 'Generate deploy targets :slot_machine:', 'command': '.buildkite/scripts/generate_deploy_targets.sh', 'key': 'gen-deploy-inputs', 'depends_on': ['get-deploy-inputs']}], 'queue': 'q1'})
    print("here we generate our pipeline")
    base_pipeline.to_yaml(filepath='generated_pipeline.yml')


def get_release_versions(service_pipelines):
    print(f"Getting release versions for {service_pipelines}")
# on a hosted agent, but we need python and the whole custom image dealio
    api_token = subprocess.run(['buildkite-agent', 'secret', 'get', 'readtokenpb'], stdout=subprocess.PIPE).stdout.decode('utf-8')

    ## local run
    # api_token = environ["BK_API_TOKEN"]
    # print(api_token)

    # headers = {'Authorization: Bearer': api_token}
    # svc_builds = requests.get('https://api.buildkite.com/v2/organizations/demo/pipelines/service-foo/builds', headers=headers)

    build_request = Request("https://api.buildkite.com/v2/organizations/demo/pipelines/service-foo/builds")
    build_request.add_header('Authorization', "Bearer " + api_token)

    svc_builds = urlopen(build_request).read()

    svc_builds_json = json.loads(svc_builds.decode('utf-8'))
    print(json.dumps(svc_builds_json))

    # get one build

    for svc_build in svc_builds_json:
        print(svc_build['url'])
        one_build_request = Request(svc_build['url']) # https://buildkite.com/docs/apis/rest-api/builds#get-a-build
        one_build_request.add_header('Authorization', "Bearer " + api_token)

        one_build_result = urlopen(build_request).read()

        one_build_json = json.loads(one_build_result.decode('utf-8'))
        # print(json.dumps(one_build_json))
        for meta_data in one_build_json:
            print(meta_data['meta_data']['rel-ver'])


def main():
    service_pipelines = ["service-foo", "service-bar", "service-web"]
    get_release_versions(service_pipelines)
    generate_pipeline()
    print("dis be in da main")

# create a dict of the values, that can be output right to a pipeline.yml right?


if __name__ == "__main__":
    main()
