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
    api_token = subprocess.run(['buildkite-agent', 'secret', 'get', 'readtokenpb'], stdout=subprocess.PIPE).stdout.decode('utf-8')

# get_api_token= subprocess.run(['buildkite-agent', 'secret', 'get', 'readtokenpb'],
#                        capture_output=True, 
#                        text=True)

    # get_api_token = subprocess.run(['echo', '${BK_API_TOKEN}'],
    #                               capture_output=True,
    #                               text=True)

    # api_token = get_api_token.stdout


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


if __name__ == "__main__":
    main()
