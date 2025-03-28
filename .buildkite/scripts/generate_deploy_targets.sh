#!/usr/bin/env bash

export SVC_FOO_VER=$(buildkite-agent meta-data get "svc-foo-ver")
export SVC_BAR_VER=$(buildkite-agent meta-data get "svc-bar-ver")
export SVC_FOO_HOSTS=$(buildkite-agent meta-data get "svc-foo-hosts")
export SVC_BAR_HOSTS=$(buildkite-agent meta-data get "svc-bar-hosts")
export SVC_FOO_PWSH=$(buildkite-agent meta-data get "svc-foo-pwsh")
export SVC_BAR_PWSH=$(buildkite-agent meta-data get "svc-bar-pwsh")

export NEW_PIPELINE=$(cat <<EOF
steps:
  - group: ":rocket: :aws: Parallel Production Deploys"
    key: "prod_deploys"
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

IFS=","

read -ra FOO_HOSTS <<< "${SVC_FOO_HOSTS}"

for FOO_HOST in "${FOO_HOSTS[@]}"
do
    echo "creating step for ${FOO_HOST} with ${SVC_FOO_VERSION} and ${SVC_FOO_PWSH}"
done

printf "%s\n" "$NEW_PIPELINE" | buildkite-agent pipeline upload
