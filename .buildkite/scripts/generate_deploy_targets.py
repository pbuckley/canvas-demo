#!/usr/bin/env python

from os import getenv, popen, system
import datetime
from benedict import benedict


def create_dynamic_step_key(prefix_fragment):
    '''
    create a dynamic step key so this dynamic pipeline generator
    can be run multiple times in the same pipeline
    we only need to go to the minute, seconds would be overkill?
    '''
    now = datetime.datetime.now()
    return prefix_fragment + '-' + now.strftime("%Y-%m-%d-%H-%M")


def main():

    if getenv("BUILDKITE_COMPUTE_TYPE") is not None:
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

    foo_prefix = [{'group': ':rocket: :windows: Service Foo Parallel Deploys', 'key': foo_step_key, 'steps': []}]
    bar_prefix = [{'group': ':rocket: :windows: Service Bar Parallel Deploys', 'key': bar_step_key, 'steps': []}]
    web_prefix = [{'group': ':rocket: :windows: Service Web Parallel Deploys', 'key': web_step_key, 'steps': []}]

    rollback_snippet = [{'block': "Rollback / Redeploy ?", 'key': rollback_block_key}, {'label': ':rewind: Rollback / Redeploy', 'key': rollback_redeploy_key, 'command': 'python .buildkite/scripts/get_releases.py', 'depends_on': [rollback_block_key]}]

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

    full_foo_hosts = []
    for foo_host in svc_foo_hosts:
        full_foo_hosts.insert(0, {'label': f':windows: Deploy Service Foo {svc_foo_ver} to {foo_host}', 'command': '.buildkite/scripts/run_mock_deploy.sh', 'retry': {'automatic': [{'exit_status': '*', 'limit': '10'}]}})
        full_foo_hosts.insert(1, {'label': f':pwsh: Run {svc_foo_pwsh} for Foo on {foo_host}', 'command': f'echo Running {svc_foo_pwsh} on {foo_host}...'})

    full_bar_hosts = []
    for bar_host in svc_bar_hosts:
        full_bar_hosts.insert(0, {'label': f':windows: Deploy Service Bar {svc_bar_ver} to {bar_host}', 'command': '.buildkite/scripts/run_mock_deploy.sh', 'retry': {'automatic': [{'exit_status': '*', 'limit': '10'}]}})
        full_bar_hosts.insert(1, {'label': f':pwsh: Run {svc_bar_pwsh} for Bar on {bar_host}', 'command': f'echo Running {svc_bar_pwsh} on {bar_host}...'})

    full_web_hosts = []
    for web_host in svc_web_hosts:
        full_web_hosts.insert(0, {'label': f':windows: Deploy Service Web {svc_web_ver} to {web_host}', 'command': '.buildkite/scripts/run_mock_deploy.sh', 'retry': {'automatic': [{'exit_status': '*', 'limit': '10'}]}})
        full_web_hosts.insert(1, {'label': f':pwsh: Run {svc_web_pwsh} for Web on {web_host}', 'command': f'echo Running {svc_web_pwsh} on {web_host}...'})

    foo_prefix[0]['steps'] = full_foo_hosts
    bar_prefix[0]['steps'] = full_bar_hosts
    web_prefix[0]['steps'] = full_web_hosts

    full_pipeline = benedict({'steps': foo_prefix + bar_prefix + web_prefix + rollback_snippet, 'queue': 'q1'})

    full_pipeline.to_yaml(filepath='newly_genned_pipeline.yml')

    if getenv("BUILDKITE_COMPUTE_TYPE") is not None:
        print("In hosted env, uploading pipeline")
        system('buildkite-agent pipeline upload newly_genned_pipeline.yml')
    else:
        print("Running locally, would have run: buildkite-agent pipeline upload newly_genned_pipeline.yml")


if __name__ == "__main__":
    main()
