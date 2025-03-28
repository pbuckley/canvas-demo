#!/usr/bin/env bash

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

export FOO_POST=$(cat <<FOOPOST
queue: "q1"
FOOPOST
)

export NEW_PIPELINE=$(cat <<EOF
steps:
  - group: ":rocket: :windows: Parallel Deploys"
    key: "parallel_deploys"
    steps:
      - label: ":ec2: prod_sm_x86_us-west-2"
        command: "echo Deploying to Intel us-west-2"
      - label: ":ec2: prod_med_arm_us-west-2"
        command: "echo Deploying to ARM us-west-2"
      - label: ":ec2: prod_lg_x86_us-east-2"
        command: "echo Deploying to Intel us-east-2"
      - label: ":ec2: prod_xl_arm_us-east-2"
        command: "echo Deploying to ARM us-east-2"
      - label: ":ec2: prod_lg_x86_us-west-1"
        command: "echo Deploying to Intel us-west-1"
      - label: ":ec2: prod_xl_arm_us-west-1"
        command: "echo Deploying to ARM us-west-1"
      - label: ":ec2: prod_med_x86_us-east-1"
        command: "echo Deploying to Intel us-east-1"
      - label: ":ec2: prod_xs_arm_us-east-1"
        command: "echo Deploying to ARM us-east-1"
      - label: ":ec2: prod_xs_x86_us-west-2"
        command: "echo Deploying to Intel us-west-2"
      - label: ":ec2: prod_xl8vcpu_arm_us-west-2"
        command: "echo Deploying to ARM us-west-2"
      - label: ":ec2: prod_xl8vcpu_x86_us-east-2"
        command: "echo Deploying to Intel us-east-2"
      - label: ":ec2: prod_lg32gb_arm_us-east-2"
        command: "echo Deploying to ARM us-east-2"
      - label: ":ec2: prod_lg32gb_x86_us-west-1"
        command: "echo Deploying to Intel us-west-1"
      - label: ":ec2: prod_xl8vcpu_arm_us-west-1"
        command: "echo Deploying to ARM us-west-1"
queue: "q1"
EOF
)

# printf "%s\n" "$NEW_PIPELINE" > pipeline-as-artifact.yml

# buildkite-agent artifact upload pipeline-as-artifact.yml

echo "+++ SVC ENV VARS"
env | grep SVC

# this is it, the loops

echo ${FOO_PRE} > newly_genned_pipeline.yml

IFS=","

read -ra FOO_HOSTS <<< "${SVC_FOO_HOSTS}"

for FOO_HOST in "${FOO_HOSTS[@]}"
do
    echo "creating step for ${FOO_HOST} with ${SVC_FOO_VER} and ${SVC_FOO_PWSH}"
    export FOO_BODY=$(cat <<FOOBOD
steps:
      - label: ":windows: Deploy Service Foo ${SVC_FOO_VER} to ${FOO_HOST}"
        command: "echo Deploying Foo ${SVC_FOO_VER} to ${FOO_HOST}..."
      - label: ":pwsh: Run Powershell postscript ${SVC_FOO_PWSH} for Foo on ${FOO_HOST}"
        command: "echo Running ${SVC_FOO_PWSH} on ${FOO_HOST}..."
FOOBOD
)
    echo ${FOOBOD} >> newly_genned_pipeline.yml
done

echo ${FOO_POST} >> newly_genned_pipeline.yml

# printf "%s\n" "$NEW_PIPELINE" | buildkite-agent pipeline upload

buildkite-agent artifact upload newly_genned_pipeline.yml

buildkite-agent pipeline upload newly_genned_pipeline.yml
