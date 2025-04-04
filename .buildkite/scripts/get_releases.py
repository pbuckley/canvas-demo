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
    # fields is a list of 3 lists, all the select->services
    # fields[0] is that one list of dicts, with key 'select'
    # how do I flatten my outer list while keeping the inner ones?

    # join 3 lists into one list? but no I need them to be list of lists
    templist = []
    for service in master_input_dict:
        templist += master_input_dict[service]
    pipeline_dict['steps'][0]['fields'] = templist
    # for service in master_input_dict:
    #     print(f"Iterating through with {service}")
    #     print(f"Fields here is {pipeline_dict['steps'][0]['fields']}")
    #     print(f"And we append: {master_input_dict[service]}")
    #     pipeline_dict['steps'][0]['fields'].append(master_input_dict[service])
    # print(f"here we generate our pipeline: {pipeline_dict}")
    # print(f"Len of fields: {len(pipeline_dict['steps'][0]['fields'])}")
    # print(f"Fields is: {pipeline_dict['steps'][0]['fields']}")
    # print(f"Len of fields[0]: {len(pipeline_dict['steps'][0]['fields'][0])}")
    # print(f"Fields[0] is: {pipeline_dict['steps'][0]['fields'][0]}")
    # pipeline_dict['steps'][0]['fields'] = [pipeline_dict['steps'][0]['fields'][0], pipeline_dict['steps'][0]['fields'][1], pipeline_dict['steps'][0]['fields'][2]]
    print(f"the new pipeline dict?: {pipeline_dict}")
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

            svc_versions_set = set()
            svc_hosts_set = set()
            svc_postscript_set = set()
            for build_details in one_build_json:
                # do not like that I am assigning over and over to svc_dict here but it works?
                svc_dict = get_release_versions_from_metadata(svc_name, build_details['meta_data'], svc_dict, svc_versions_set)
                host_dict = get_hosts_from_metadata(svc_name, build_details['meta_data'], host_dict, svc_hosts_set)
                post_dict = get_postscript_from_metadata(svc_name, build_details['meta_data'], post_dict, svc_postscript_set)
    return svc_dict, host_dict, post_dict


# obvi these translate fns have a lot in common, could be refactored in the future
def translate_service_versions_to_bk_yaml(service, all_services_and_versions):
    # as I compare this to the base_pipeline benedict we have currently
    # I think we need to have all the metadata in the service pipeline
    # otherwise how will we pair the hosts and pwsh with the versions?
    # I think it will be too brittle to shoehorn just the versions in there
    # we need to take "everything" for each of our fields - one for each service -
    # and iterate over them here
    generated_svc_yaml = []
    for k, v in all_services_and_versions.items():
        if k == service:
            keysafe_k = k.replace(" ", "-").lower()
            option_list = []
            for ver in v:
                option_list.append({"label": ver, "value": ver})
            generated_svc_yaml.append({"select": f"{k} version", "key": f"{keysafe_k}-ver", "options": option_list})
            # new problem, at this point this contains duplicates, I have 5 'select's!!!
            print(f"{k} generated yaml is: {generated_svc_yaml}")
    return generated_svc_yaml


def translate_service_hosts_to_bk_yaml(service, all_services_and_hosts):
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
        if k == service: # only do translation for the one service we are passed as key
            keysafe_k = k.replace(" ", "-").lower()
            option_list = ",".join(v)
            generated_svc_yaml = {"text": f"{k} host list", "key": f"{keysafe_k}-hosts", "default": option_list, "hint": f"Comma separated list of hosts to deploy {k} onto", "required": True}
            print(generated_svc_yaml)
    return generated_svc_yaml


def translate_service_postscripts_to_bk_yaml(service, all_services_and_pwsh):
    # as I compare this to the base_pipeline benedict we have currently
    # I think we need to have all the metadata in the service pipeline
    # otherwise how will we pair the hosts and pwsh with the versions?
    # I think it will be too brittle to shoehorn just the versions in there
    # we need to take "everything" for each of our fields - one for each service -
    # and iterate over them here
    example_dict = {"text": ":pwsh: Service Foo post config script", "key": "svc-foo-pwsh", "hint": "Provide filename for optional PS1 to run post deploy.", "required": False, "default": "ServiceFooDefault.PS1"}
    for k, v in all_services_and_pwsh.items():
        if k == service:
            keysafe_k = k.replace(" ", "-").lower()
            option_list = ",".join(v)
            generated_svc_yaml = {"text": f"{k} post config script", "key": f"{keysafe_k}-pwsh", "default": option_list, "hint": "Provide filename for optional PS1 to run post deploy.", "required": False}
            print(generated_svc_yaml)
    return generated_svc_yaml


def main():
    org_name = "demo"
    given_tag = "deployable-svc"
    api_token = fetch_bk_api_token()
    # we can use a step key with a date-time dash separated
    # this will solve our rollback issue
    # and I can do it all here in python
    # BUILDKITE_STEP_KEY="foo-app-key-2025-04-04-11-56"
    input_step_key = create_dynamic_step_key('get-deploy-inputs')
    deploy_step_key = create_dynamic_step_key('gen-deploy-inputs')
    print(f"using input_step_key of: {input_step_key}")
    print(f"using deploy_step_key of: {deploy_step_key}")
    base_pipeline = benedict({'steps': [{'input': 'Provide versions and targets for :dotnet: deploy', 'key': input_step_key}, {'label': 'Generate deploy targets :slot_machine:', 'command': '.buildkite/scripts/generate_deploy_targets.sh', 'key': deploy_step_key, 'depends_on': [input_step_key]}], 'queue': 'q1'})
    tagged_pipelines = get_tagged_pipelines(api_token, org_name, given_tag)
    # print(f"Tagged pipelines: {tagged_pipelines}")
    version_dict_of_all_svcs, host_dict_of_all_svcs, post_dict_of_all_svcs = get_release_versions(api_token, org_name, tagged_pipelines)
    print(f"Version dict of all services: {version_dict_of_all_svcs}")
    print(f"Host dict of all services: {host_dict_of_all_svcs}")
    print(f"Post dict of all services: {post_dict_of_all_svcs}")
    master_input_dict = {key: [] for key in version_dict_of_all_svcs}
    for service in master_input_dict:
        master_input_dict[service] = []
        # so I am passing service as a param, could I not just pass the value of the version_dict_of_all_svcs that was the key I want, like version_dict_of_all_svcs[service] and similarly achieve the same limiting I want?
        print(f"Generating master_input_dict for {service}, version_dict_of_all_svcs is: {version_dict_of_all_svcs}")
        master_input_dict[service].append(translate_service_versions_to_bk_yaml(service, version_dict_of_all_svcs))
        master_input_dict[service].append(translate_service_hosts_to_bk_yaml(service, host_dict_of_all_svcs))
        master_input_dict[service].append(translate_service_postscripts_to_bk_yaml(service, post_dict_of_all_svcs))
        master_input_dict[service][0] = master_input_dict[service][0][0]
    # translate_service_versions_to_bk_yaml(dict_of_all_svcs)
    print(f"master input dict?: {master_input_dict}")
    # hacky to do it here, but we need to remove one layer of listification (try it above in an iteration)
    # master_input_dict['service-web'][0] = master_input_dict['service-web'][0][0]
    print(f"revised master input dict?: {master_input_dict}")
    generate_pipeline(base_pipeline, master_input_dict)

    if getenv("BUILDKITE_COMPUTE_TYPE") is not None:
        print("In hosted env, uploading pipeline")
        system('buildkite-agent pipeline upload generated_pipeline.yml')
    else:
        print("Running locally, would have run: buildkite-agent pipeline upload generated_pipeline.yml")


if __name__ == "__main__":
    main()
