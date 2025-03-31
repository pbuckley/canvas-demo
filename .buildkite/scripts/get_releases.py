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


def get_tagged_pipelines(api_token, org_name, given_tag):
    '''
    get all pipelines with a given tag, e.g. deployable-svc
    this way, the pipelines do not even need to follow a naming convention
    given_tag: a string with a valid tag
    '''
    print(f"Getting pipelines containing {given_tag}")
    # I want to support pagination but `demo` org only has 30 pipelines, under the default single page limit
    headers = {'Authorization': "Bearer " + api_token}
    r = requests.get(f"https://api.buildkite.com/v2/organizations/{org_name}/pipelines", headers=headers)
    full_list = r.json()
    filtered_list = [item for item in full_list if item.get('tags') and given_tag in item['tags']]
    return filtered_list


def get_release_versions(api_token, org_name, deployable_service_pipelines):
    release_version_md_name = "rel-ver" # I want to prefix with deploy- eventually so deploy-rel-ver

    svc_dict = {}
    for pipeline_details in deployable_service_pipelines:
        named_pipeline = pipeline_details['name']
        print(f"Getting builds for {pipeline_details['name']}...")
        build_request = Request(f"https://api.buildkite.com/v2/organizations/{org_name}/pipelines/{named_pipeline}/builds")
        build_request.add_header('Authorization', "Bearer " + api_token)

        svc_builds = urlopen(build_request).read()

        svc_builds_json = json.loads(svc_builds.decode('utf-8'))
        # print(f"Our whole svc_builds_json {json.dumps(svc_builds_json)}")

        for svc_build in svc_builds_json:
            svc_name = svc_build['pipeline']['name']
            svc_url = svc_build['url']
            print(f"Service of name: {svc_name} has url: {svc_url}")
            one_build_request = Request(svc_build['url']) # https://buildkite.com/docs/apis/rest-api/builds#get-a-build
            one_build_request.add_header('Authorization', "Bearer " + api_token)

            one_build_result = urlopen(build_request).read()
            one_build_json = json.loads(one_build_result.decode('utf-8'))
            # print(json.dumps(one_build_json))

            # {'select': 'Service Foo version', 'key': 'svc-foo-ver', 'options': [{'label': '1.33', 'value': '1.33'}, {'label': '1.35', 'value': '1.35'}, {'label': '1.38', 'value': '1.38'}]}
            # template_dict = {'select': 'Service Foo version', 'key': 'svc-foo-ver', 'options': [{'label': '1.33', 'value': '1.33'}, {'label': '1.35', 'value': '1.35'}, {'label': '1.38', 'value': '1.38'}]}
            # so we reconstruct ^ this and populate with our name and release versions?
            # and we do it for multiples... then we need to inject into our base_pipeline somehow?
            # svc_dict = template_dict
            # svc_dict['select'] = svc_name + " version"
            # svc_dict['key'] = svc_name + "-ver" # need to control for key character restrictions
            svc_build_versions = set()

            for build_details in one_build_json:
                print(f"Full metadata for {svc_name}: {build_details['meta_data']}")
                release_version = build_details['meta_data'][release_version_md_name]
                print(f"Found a {svc_name} release version: {release_version}")
                svc_build_versions.add(release_version)
            svc_dict[svc_name] = sorted(svc_build_versions)

    return svc_dict


# obvi these translate fns have a lot in common, could be refactored in the future
def translate_service_versions_to_bk_yaml(all_services_and_versions):
    # as I compare this to the base_pipeline benedict we have currently
    # I think we need to have all the metadata in the service pipeline
    # otherwise how will we pair the hosts and pwsh with the versions?
    # I think it will be too brittle to shoehorn just the versions in there
    # we need to take "everything" for each of our fields - one for each service -
    # and iterate over them here
    for k, v in all_services_and_versions.items():
        option_list = []
        for ver in v:
            option_list.append({"label": ver, "value": ver})
        generated_svc_yaml = {"select": f"{k} version", "key": f"{k}-ver", "options": option_list}
        print(generated_svc_yaml)


def translate_service_hosts_to_bk_yaml(all_services_and_hosts):
    # as I compare this to the base_pipeline benedict we have currently
    # I think we need to have all the metadata in the service pipeline
    # otherwise how will we pair the hosts and pwsh with the versions?
    # I think it will be too brittle to shoehorn just the versions in there
    # we need to take "everything" for each of our fields - one for each service -
    # and iterate over them here
    example_dict = {"text": ":windows: Service Foo Host List", "key": "svc-foo-hosts", "hint": "Comma separated list of hosts to deploy Service Foo onto", "required": True, "default": "iis_server01,iis_server02,iis_server03"}
    # I want to keep the emoji - do I make that metadata, too, or can I go with the pipeline's emoji
    # and grab from one of our existing API calls to reuse it here?
    for k, v in all_services_and_hosts.items():
        option_list = [] # can be a scalar string as csv I bet, no need for a list here
        generated_svc_yaml = {"text": f"{k} host list", "key": f"{k}-hosts", "default": option_list, "hint": f"Comma separated list of hosts to deploy {k} onto", "required": True,}
        print(generated_svc_yaml)


def translate_service_pwsh_to_bk_yaml(all_services_and_pwsh):
    # as I compare this to the base_pipeline benedict we have currently
    # I think we need to have all the metadata in the service pipeline
    # otherwise how will we pair the hosts and pwsh with the versions?
    # I think it will be too brittle to shoehorn just the versions in there
    # we need to take "everything" for each of our fields - one for each service -
    # and iterate over them here
    example_dict = {"text": ":pwsh: Service Foo post config script", "key": "svc-foo-pwsh", "hint": "Provide filename for optional PS1 to run post deploy.", "required": False, "default": "ServiceFooDefault.PS1"}
    for k, v in all_services_and_pwsh.items():
        option_list = [] # can be a scalar string as csv I bet, no need for a list here
        generated_svc_yaml = {"text": f"{k} post config script", "key": f"{k}-pwsh", "default": option_list, "hint": "Provide filename for optional PS1 to run post deploy.", "required": False,}
        print(generated_svc_yaml)


def main():
    org_name = "demo"
    given_tag = "deployable-svc"
    api_token = fetch_bk_api_token()
    base_pipeline = benedict({'steps': [{'input': 'Provide versions and targets for :dotnet: deploy', 'key': 'get-deploy-inputs', 'fields': [{'select': 'Service Foo version', 'key': 'svc-foo-ver', 'options': [{'label': '1.33', 'value': '1.33'}, {'label': '1.35', 'value': '1.35'}, {'label': '1.38', 'value': '1.38'}]}, {'text': ':windows: Service Foo Host List', 'key': 'svc-foo-hosts', 'hint': 'Comma separated list of hosts to deploy Service Foo onto', 'required': True, 'default': 'iis_server01,iis_server02,iis_server03'}, {'text': ':pwsh: Service Foo post config script', 'key': 'svc-foo-pwsh', 'hint': 'Provide filename for optional PS1 to run post deploy.', 'required': False, 'default': 'ServiceFooDefault.PS1'}, {'select': 'Service Bar version', 'key': 'svc-bar-ver', 'options': [{'label': '2.54', 'value': '2.54'}, {'label': '2.79', 'value': '2.79'}, {'label': '3.01RC', 'value': '3.01RC'}]}, {'text': ':pwsh: Service Bar post config script', 'key': 'svc-bar-pwsh', 'hint': 'Provide filename for optional PS1 to run post deploy.', 'required': False, 'default': 'ServiceBarDefault.PS1'}, {'text': ':windows: Service Bar Host List', 'key': 'svc-bar-hosts', 'hint': 'Comma separated list of hosts to deploy Service Bar onto', 'required': True, 'default': 'file_server01,file_server02,file_server03'}, {'select': 'Service Web version', 'key': 'svc-web-ver', 'options': [{'label': '7.45', 'value': '7.45'}, {'label': '8.19', 'value': '8.19'}, {'label': '8.04a', 'value': '8.04a'}]}, {'text': ':windows: Service Web Host List', 'key': 'svc-web-hosts', 'hint': 'Comma separated list of hosts to deploy Service Web onto', 'required': True, 'default': 'web_server1103,web_server2984,web_server1849'}, {'text': ':pwsh: Service Web post config script', 'key': 'svc-web-pwsh', 'hint': 'Provide filename for optional PS1 to run post deploy.', 'required': False, 'default': 'ServiceWebDefault.PS1'}]}, {'label': 'Generate deploy targets :slot_machine:', 'command': '.buildkite/scripts/generate_deploy_targets.sh', 'key': 'gen-deploy-inputs', 'depends_on': ['get-deploy-inputs']}], 'queue': 'q1'})

    tagged_pipelines = get_tagged_pipelines(api_token, org_name, given_tag)
    # print(f"Tagged pipelines: {tagged_pipelines}")
    dict_of_all_svcs = get_release_versions(api_token, org_name, tagged_pipelines)
    print(f"Dict of all services: {dict_of_all_svcs}")
    translate_service_versions_to_bk_yaml(dict_of_all_svcs)
    # need to implement these, but our service-* pipelines need the metadata present first
    # translate_service_hosts_to_bk_yaml(dict_of_all_svcs)
    # translate_service_pwsh_to_bk_yaml(dict_of_all_svcs)
    generate_pipeline(base_pipeline)
    print("made it to end of main fn")


if __name__ == "__main__":
    main()
