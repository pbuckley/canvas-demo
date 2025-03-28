#!/usr/bin/env bash

IFS=","

export SVC_FOO_VER=$(buildkite-agent meta-data get "svc-foo-ver")
export SVC_BAR_VER=$(buildkite-agent meta-data get "svc-bar-ver")
export SVC_FOO_HOSTS=$(buildkite-agent meta-data get "svc-foo-hosts")
export SVC_BAR_HOSTS=$(buildkite-agent meta-data get "svc-bar-hosts")
export SVC_FOO_PWSH=$(buildkite-agent meta-data get "svc-foo-pwsh")
export SVC_BAR_PWSH=$(buildkite-agent meta-data get "svc-bar-pwsh")

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
        command: "echo Deploying Foo ${SVC_FOO_VER} to ${FOO_HOST}..."
      - label: ":pwsh: Run Powershell postscript ${SVC_FOO_PWSH} for Foo on ${FOO_HOST}"
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
        command: "echo Deploying Bar ${SVC_BAR_VER} to ${BAR_HOST}..."
      - label: ":pwsh: Run Powershell postscript ${SVC_BAR_PWSH} for Bar on ${BAR_HOST}"
        command: "echo Running ${SVC_BAR_PWSH} on ${BAR_HOST}..."
BARBOD
)
    echo ${BAR_BODY} >> newly_genned_pipeline.yml
done

echo ${ALL_POST} >> newly_genned_pipeline.yml

echo "+++ Now with ALLPOST"
cat newly_genned_pipeline.yml

buildkite-agent artifact upload newly_genned_pipeline.yml

buildkite-agent pipeline upload newly_genned_pipeline.yml

rm -f newly_genned_pipeline.yml
