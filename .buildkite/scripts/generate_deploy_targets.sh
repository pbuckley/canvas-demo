#!/usr/bin/env bash

IFS=","

export SVC_FOO_VER=$(buildkite-agent meta-data get "svc-foo-ver")
export SVC_BAR_VER=$(buildkite-agent meta-data get "svc-bar-ver")
export SVC_WEB_VER=$(buildkite-agent meta-data get "svc-web-ver")
export SVC_FOO_HOSTS=$(buildkite-agent meta-data get "svc-foo-hosts")
export SVC_BAR_HOSTS=$(buildkite-agent meta-data get "svc-bar-hosts")
export SVC_WEB_HOSTS=$(buildkite-agent meta-data get "svc-web-hosts")
export SVC_FOO_PWSH=$(buildkite-agent meta-data get "svc-foo-pwsh")
export SVC_BAR_PWSH=$(buildkite-agent meta-data get "svc-bar-pwsh")
export SVC_WEB_PWSH=$(buildkite-agent meta-data get "svc-web-pwsh")

export FOO_PRE=$(cat <<FOOPRE
steps:
  - group: ":rocket: :windows: Service Foo Parallel Deploys"
    key: "foo_deploys"
    steps:
FOOPRE
)

export BAR_PRE=$(cat <<BARPRE
  - group: ":rocket: :windows: Service Bar Parallel Deploys"
    key: "bar_deploys"
    steps:
BARPRE
)

export WEB_PRE=$(cat <<WEBPRE
  - group: ":rocket: :windows: Service Web Parallel Deploys"
    key: "web_deploys"
    steps:
WEBPRE
)

export ALL_POST=$(cat <<ALLPOST
queue: "q1"
ALLPOST
)

echo "+++ SVC ENV VARS"
env | grep SVC

# this is it, the loops

printf "%s\n" "$FOO_PRE" > newly_genned_pipeline.yml

echo "+++ With just the FOO_PRE"
cat newly_genned_pipeline.yml

read -ra FOO_HOSTS <<< "${SVC_FOO_HOSTS}"

for FOO_HOST in "${FOO_HOSTS[@]}"
do
    echo "creating step for ${FOO_HOST} with ${SVC_FOO_VER} and ${SVC_FOO_PWSH}"
    export FOO_BODY=$(cat <<FOOBOD
      - label: ":windows: Deploy Service Foo ${SVC_FOO_VER} to ${FOO_HOST}"
        command: ".buildkite/scripts/run_mock_deploy.sh"
        retry:
          automatic:
            - exit_status: 4
              limit: 2
            - exit_status: *
              limit: 3
      - label: ":pwsh: Run ${SVC_FOO_PWSH} for Foo on ${FOO_HOST}"
        command: "echo Running ${SVC_FOO_PWSH} on ${FOO_HOST}..."
FOOBOD
)
    echo ${FOO_BODY} >> newly_genned_pipeline.yml
done

echo "+++ NOW WITH FOOBOD"
cat newly_genned_pipeline.yml

echo ${BAR_PRE} >> newly_genned_pipeline.yml

read -ra BAR_HOSTS <<< "${SVC_BAR_HOSTS}"

for BAR_HOST in "${BAR_HOSTS[@]}"
do
    echo "creating step for ${BAR_HOST} with ${SVC_BAR_VER} and ${SVC_BAR_PWSH}"
    export BAR_BODY=$(cat <<BARBOD
      - label: ":windows: Deploy Service Bar ${SVC_BAR_VER} to ${BAR_HOST}"
        command: ".buildkite/scripts/run_mock_deploy.sh"
        retry:
          automatic:
            - exit_status: 3
              limit: 2
            - exit_status: *
              limit: 4
      - label: ":pwsh: Run ${SVC_BAR_PWSH} for Bar on ${BAR_HOST}"
        command: "echo Running ${SVC_BAR_PWSH} on ${BAR_HOST}..."
BARBOD
)
    echo ${BAR_BODY} >> newly_genned_pipeline.yml
done

echo ${WEB_PRE} >> newly_genned_pipeline.yml

read -ra WEB_HOSTS <<< "${SVC_WEB_HOSTS}"

for WEB_HOST in "${WEB_HOSTS[@]}"
do
    echo "creating step for ${WEB_HOST} with ${SVC_WEB_VER} and ${SVC_WEB_PWSH}"
    export WEB_BODY=$(cat <<WEBBOD
      - label: ":windows: Deploy Service Web ${SVC_WEB_VER} to ${WEB_HOST}"
        command: ".buildkite/scripts/run_mock_deploy.sh"
        retry:
          automatic:
            - exit_status: 1
              limit: 1
            - exit_status: *
              limit: 2
      - label: ":pwsh: Run ${SVC_WEB_PWSH} for Web on ${WEB_HOST}"
        command: "echo Running ${SVC_WEB_PWSH} on ${WEB_HOST}..."
WEBBOD
)
    echo ${WEB_BODY} >> newly_genned_pipeline.yml
done

echo ${ALL_POST} >> newly_genned_pipeline.yml

echo "+++ Now with ALLPOST"
cat newly_genned_pipeline.yml

buildkite-agent artifact upload newly_genned_pipeline.yml

buildkite-agent pipeline upload newly_genned_pipeline.yml

rm -f newly_genned_pipeline.yml
