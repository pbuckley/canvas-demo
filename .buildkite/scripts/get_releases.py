#!/usr/bin/env python

# call the Buildkite API to get releases for our services

import subprocess
# import urllib.request
from urllib.request import Request, urlopen
from os import environ
import json


def main():
    service_pipelines = ["service-foo", "service-bar", "service-web"]

# on a hosted agent
    # api_token = subprocess.run(['buildkite-agent', 'secret', 'get', 'readtokenpb'], stdout=subprocess.PIPE).stdout.decode('utf-8')

    ## local run
    api_token = environ["BK_API_TOKEN"]
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
        one_build_request = Request(svc_build['url'])
        one_build_request.add_header('Authorization', "Bearer " + api_token)

        one_build_result = urlopen(build_request).read()

        one_build_json = json.loads(one_build_result.decode('utf-8'))
        # print(json.dumps(one_build_json))
        for meta_data in one_build_json:
            print(meta_data['meta_data']['rel-ver'])

# came so far and got so close but we just have the meta_data and not the yaml to generate it :(

    # https://api.buildkite.com/v2/organizations/{org.slug}/pipelines/{pipeline.slug}/builds/{number}"

if __name__ == "__main__":
    main()
