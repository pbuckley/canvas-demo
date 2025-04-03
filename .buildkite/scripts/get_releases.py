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


def get_release_versions_from_metadata(svc_name, full_metadata, svc_dict, svc_build_versions):
    release_version_md_name = "rel-ver" # I want to prefix with deploy- eventually so deploy-rel-ver

    print(f"Full metadata for {svc_name}: {full_metadata}")
    release_version = full_metadata[release_version_md_name]
    print(f"Found a {svc_name} release version: {release_version}")
    svc_build_versions.add(release_version)
    svc_dict[svc_name] = sorted(svc_build_versions)

    return svc_dict


def get_hosts_from_metadata(svc_name, full_metadata, host_dict, svc_hosts_set):
    hosts_md_name = "deploy-hosts"

    if full_metadata.get(hosts_md_name) is not None:
        print(f"Full metadata for {svc_name}: {full_metadata}")
        svc_hosts = [host.strip() for host in full_metadata[hosts_md_name].split(",")]
        print(f"{svc_name} has svc_hosts as a list: {svc_hosts}")
        svc_hosts_set.update(svc_hosts)
        print(f"Found a {svc_name} host list: {svc_hosts}")
        host_dict[svc_name] = sorted(svc_hosts_set)

    return host_dict


def get_postscript_from_metadata(svc_name, full_metadata, post_dict, svc_postscript):
    postscript_md_name = "deploy-post-script"

    if full_metadata.get(postscript_md_name) is not None:
        print(f"Full metadata for {svc_name}: {full_metadata}")
        postscript = full_metadata[postscript_md_name]
        print(f"Found a {svc_name} postscript: {postscript}")
        svc_postscript.add(postscript)
        post_dict[svc_name] = sorted(svc_postscript)

    return post_dict


def get_release_versions(api_token, org_name, deployable_service_pipelines):
    # currently, this fn is tailored to release version
    # what if we generic-ified it, made it just grab the metadata from all the builds
    # then we return that metadata, and we can take our 3 (or more)
    # passes over it to translate_service_versions_to_bk_yaml (and hosts, pwsh, etc)
    # given that this fn collapses rel-ver into a set so we don't have dupes,
    # would we do the same with the generic version? or would the translation deal with dupes
    # each in their own way for ver/host/pwsh?
    # maybe this fn becomes as simple as "get the metadata for all the builds" (a list)
    # and the 3 translate fns can act on it as they like, dealing with whatever complexity
    # and differentiation that they need to specific to their demesnes (again ver/host/pwsh)
    # I think I like this approach of "get_metadata" and dispatch to each type (and their corresponding
    # complexity) better - that way the get_metadata stays the same no matter how much
    # we add or change, and the individual translate fns will handle their demesnes

    # ok, all well and good sounding, but the problem is we need to iterate over
    # multiple builds to collect metadata from them all
    # so we need a collection/collector (list?) for the metadata
    # but right now we're distilling into a dict of the {service-name: [<release versions>], ...}

    svc_dict = {}
    host_dict = {}
    post_dict = {}
    for pipeline_details in deployable_service_pipelines:
        build_request = Request(pipeline_details['url'] + "/builds")
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

            svc_build_versions = set()
            svc_hosts_set = set()
            svc_postscript = set()
            for build_details in one_build_json:
                # do not like that I am assigning over and over to svc_dict here but it works?
                svc_dict = get_release_versions_from_metadata(svc_name, build_details['meta_data'], svc_dict, svc_build_versions)
                host_dict = get_hosts_from_metadata(svc_name, build_details['meta_data'], host_dict, svc_hosts_set)
                post_dict = get_postscript_from_metadata(svc_name, build_details['meta_data'], post_dict, svc_postscript)
    return svc_dict, host_dict, post_dict


# obvi these translate fns have a lot in common, could be refactored in the future
def translate_service_versions_to_bk_yaml(all_services_and_versions):
    # as I compare this to the base_pipeline benedict we have currently
    # I think we need to have all the metadata in the service pipeline
    # otherwise how will we pair the hosts and pwsh with the versions?
    # I think it will be too brittle to shoehorn just the versions in there
    # we need to take "everything" for each of our fields - one for each service -
    # and iterate over them here
    for k, v in all_services_and_versions.items():
        keysafe_k = k.replace(" ", "-").lower()
        option_list = []
        for ver in v:
            option_list.append({"label": ver, "value": ver})
        generated_svc_yaml = {"select": f"{k} version", "key": f"{keysafe_k}-ver", "options": option_list}
        print(f"{k} generated yaml is: {generated_svc_yaml}")
    return generated_svc_yaml


def translate_service_hosts_to_bk_yaml(all_services_and_hosts):
    # as I compare this to the base_pipeline benedict we have currently
    # I think we need to have all the metadata in the service pipeline
    # otherwise how will we pair the hosts and pwsh with the versions?
    # I think it will be too brittle to shoehorn just the versions in there
    # we need to take "everything" for each of our fields - one for each service -
    # and iterate over them here
    incoming_dict = {'service-web': ['websrv10', 'websrv13', 'websrv15', 'websrv78', 'websrv9'], 'Bar Service': ['filesrv06', 'filesrv18', 'iis_server02', 'iis_server32', 'iis_srv12', 'iis_srv25'], 'Foo App': ['appsrv01', 'appsrv02', 'appsrv03', 'appsrv04', 'appsrv05', 'appsrv06']}
    example_dict = {"text": ":windows: Service Foo Host List", "key": "svc-foo-hosts", "hint": "Comma separated list of hosts to deploy Service Foo onto", "required": True, "default": "iis_server01,iis_server02,iis_server03"}
    # I want to keep the emoji - do I make that metadata, too, or can I go with the pipeline's emoji
    # and grab from one of our existing API calls to reuse it here?
    for k, v in all_services_and_hosts.items():
        keysafe_k = k.replace(" ", "-").lower()
        option_list = ",".join(v)
        generated_svc_yaml = {"text": f"{k} host list", "key": f"{keysafe_k}-hosts", "default": option_list, "hint": f"Comma separated list of hosts to deploy {k} onto", "required": True}
        print(generated_svc_yaml)
    return generated_svc_yaml


def translate_service_postscripts_to_bk_yaml(all_services_and_pwsh):
    # as I compare this to the base_pipeline benedict we have currently
    # I think we need to have all the metadata in the service pipeline
    # otherwise how will we pair the hosts and pwsh with the versions?
    # I think it will be too brittle to shoehorn just the versions in there
    # we need to take "everything" for each of our fields - one for each service -
    # and iterate over them here
    example_dict = {"text": ":pwsh: Service Foo post config script", "key": "svc-foo-pwsh", "hint": "Provide filename for optional PS1 to run post deploy.", "required": False, "default": "ServiceFooDefault.PS1"}
    for k, v in all_services_and_pwsh.items():
        keysafe_k = k.replace(" ", "-").lower()
        option_list = [] # can be a scalar string as csv I bet, no need for a list here
        generated_svc_yaml = {"text": f"{k} post config script", "key": f"{keysafe_k}-pwsh", "default": option_list, "hint": "Provide filename for optional PS1 to run post deploy.", "required": False}
        print(generated_svc_yaml)
    return generated_svc_yaml


def main():
    org_name = "demo"
    given_tag = "deployable-svc"
    api_token = fetch_bk_api_token()
    base_pipeline = benedict({'steps': [{'input': 'Provide versions and targets for :dotnet: deploy', 'key': 'get-deploy-inputs', 'fields': [{'select': 'Service Foo version', 'key': 'svc-foo-ver', 'options': [{'label': '1.33', 'value': '1.33'}, {'label': '1.35', 'value': '1.35'}, {'label': '1.38', 'value': '1.38'}]}, {'text': ':windows: Service Foo Host List', 'key': 'svc-foo-hosts', 'hint': 'Comma separated list of hosts to deploy Service Foo onto', 'required': True, 'default': 'iis_server01,iis_server02,iis_server03'}, {'text': ':pwsh: Service Foo post config script', 'key': 'svc-foo-pwsh', 'hint': 'Provide filename for optional PS1 to run post deploy.', 'required': False, 'default': 'ServiceFooDefault.PS1'}, {'select': 'Service Bar version', 'key': 'svc-bar-ver', 'options': [{'label': '2.54', 'value': '2.54'}, {'label': '2.79', 'value': '2.79'}, {'label': '3.01RC', 'value': '3.01RC'}]}, {'text': ':pwsh: Service Bar post config script', 'key': 'svc-bar-pwsh', 'hint': 'Provide filename for optional PS1 to run post deploy.', 'required': False, 'default': 'ServiceBarDefault.PS1'}, {'text': ':windows: Service Bar Host List', 'key': 'svc-bar-hosts', 'hint': 'Comma separated list of hosts to deploy Service Bar onto', 'required': True, 'default': 'file_server01,file_server02,file_server03'}, {'select': 'Service Web version', 'key': 'svc-web-ver', 'options': [{'label': '7.45', 'value': '7.45'}, {'label': '8.19', 'value': '8.19'}, {'label': '8.04a', 'value': '8.04a'}]}, {'text': ':windows: Service Web Host List', 'key': 'svc-web-hosts', 'hint': 'Comma separated list of hosts to deploy Service Web onto', 'required': True, 'default': 'web_server1103,web_server2984,web_server1849'}, {'text': ':pwsh: Service Web post config script', 'key': 'svc-web-pwsh', 'hint': 'Provide filename for optional PS1 to run post deploy.', 'required': False, 'default': 'ServiceWebDefault.PS1'}]}, {'label': 'Generate deploy targets :slot_machine:', 'command': '.buildkite/scripts/generate_deploy_targets.sh', 'key': 'gen-deploy-inputs', 'depends_on': ['get-deploy-inputs']}], 'queue': 'q1'})

    tagged_pipelines = get_tagged_pipelines(api_token, org_name, given_tag)
    # print(f"Tagged pipelines: {tagged_pipelines}")
    version_dict_of_all_svcs, host_dict_of_all_svcs, post_dict_of_all_svcs = get_release_versions(api_token, org_name, tagged_pipelines)
    print(f"Version dict of all services: {version_dict_of_all_svcs}")
    print(f"Host dict of all services: {host_dict_of_all_svcs}")
    print(f"Post dict of all services: {post_dict_of_all_svcs}")
    master_input_dict = {key: [] for key in version_dict_of_all_svcs}
    # slight problem, each entry of `service-web`, `Bar Service`, and `Foo App` have the versions and hosts from Foo App only
    # and the first two shouldn't have any of them XD
    # most likely an assignment issue?
    # can I operate on just my key, and only translate that?
    # sure I might end up calling translate_ fn more often but I just want the one service I'm doing
    for service in master_input_dict:
        master_input_dict[service] = []
        master_input_dict[service].append(translate_service_versions_to_bk_yaml(version_dict_of_all_svcs))
        master_input_dict[service].append(translate_service_hosts_to_bk_yaml(host_dict_of_all_svcs))
        # master_input_dict[service].append(translate_service_postscripts_to_bk_yaml(post_dict_of_all_svcs))
    # translate_service_versions_to_bk_yaml(dict_of_all_svcs)
    print(f"Master input dict?: {master_input_dict}")
    generate_pipeline(base_pipeline)
    print("made it to end of main fn")


if __name__ == "__main__":
    main()
