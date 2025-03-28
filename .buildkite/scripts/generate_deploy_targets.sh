#!/usr/bin/env bash

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

echo ${NEW_PIPELINE} | buildkite-agent pipeline upload
