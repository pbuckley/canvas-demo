#!/usr/bin/env python

import argparse
from os import getenv, popen, system
from datetime import datetime, timedelta
import json
import requests
import re
import time
from collections import defaultdict, Counter


def fetch_bk_api_token():
    """Fetch Buildkite API token from either secret or environment"""
    if getenv("BUILDKITE_COMPUTE_TYPE") is not None:
        print("In hosted env, fetching bk api token from secret")
        return str.strip(popen("buildkite-agent secret get readtokenpb").read())
    elif getenv("BUILDKITE_API_TOKEN"):
        print("Using BUILDKITE_API_TOKEN from environment")
        return getenv("BUILDKITE_API_TOKEN")
    else:
        print("❌ No API token found - set BUILDKITE_API_TOKEN environment variable")
        return None


def get_current_build_data(build_id=None, org_name=None, pipeline_name=None):
    """
    Get the current build data from Buildkite API to analyze deployment results.
    Returns build data with all job information.

    Args:
        build_id: Optional build ID for local testing
        org_name: Optional org name for local testing
        pipeline_name: Optional pipeline name for local testing
    """
    if build_id and org_name and pipeline_name:
        # Local testing mode - use provided parameters
        constructed_url = f"https://api.buildkite.com/v2/organizations/{org_name}/pipelines/{pipeline_name}/builds/{build_id}"
        print(f"🔧 LOCAL MODE: Fetching build data from {constructed_url}")
    else:
        # Production mode - use environment variables
        org_name = getenv("BUILDKITE_ORGANIZATION_SLUG")
        pipeline_name = getenv("BUILDKITE_PIPELINE_SLUG")
        build_number = getenv("BUILDKITE_BUILD_NUMBER")

        if not all([org_name, pipeline_name, build_number]):
            print("Missing required environment variables for API call")
            return None

        constructed_url = f"https://api.buildkite.com/v2/organizations/{org_name}/pipelines/{pipeline_name}/builds/{build_number}"
        print(f"🚀 PRODUCTION MODE: Fetching build data from {constructed_url}")

    api_token = fetch_bk_api_token()
    if not api_token:
        print("❌ Failed to get API token")
        return None

    headers = {'Authorization': "Bearer " + api_token}

    try:
        r = requests.get(constructed_url, headers=headers)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        print(f"Error fetching build data: {e}")
        return None


def get_metadata_artifact():
    """
    Load the metadata artifact to get service configuration information.
    This helps us understand what services were supposed to be deployed.
    """
    if getenv("BUILDKITE_COMPUTE_TYPE") is not None:
        print("Downloading metadata artifact...")
        artifact_pattern = "json-meta-data*.json"
        download_cmd = f'buildkite-agent artifact download "{artifact_pattern}" .'
        popen(download_cmd).read()

    # Get the most recent artifact file
    json_filename_cmd = "ls -1 json-meta-data-*.json | sort -r | head -1"
    json_filename = str.strip(popen(json_filename_cmd).read())

    if not json_filename:
        print("WARNING: No metadata artifact found - summary will be limited")
        return None

    try:
        with open(json_filename, 'r') as json_file:
            return json.load(json_file)
    except (IOError, json.JSONDecodeError) as e:
        print(f"Error reading metadata artifact: {e}")
        return None


def should_stop_monitoring(build_data, deployment_results):
    """
    Determine if we should stop live monitoring based on pipeline state.

    FIXED: Only stops when:
    1. Build is in terminal state (passed/failed/canceled), OR
    2. All deployment jobs are complete AND rollback decision point is reached

    This prevents premature stopping when rollback step appears but deployments are still running.

    Returns:
        tuple: (should_stop: bool, reason: str)
    """
    build_state = build_data.get('state', 'unknown')

    print(f"\n=== DEBUG: Stop Monitoring Check (FIXED) ===")
    print(f"Build state: {build_state}")

    # Stop if build is in terminal state
    if build_state in ['passed', 'failed', 'canceled']:
        return True, f"Build finished with state: {build_state}"

    # Check if we have any deployments still running or pending
    active_deployments = 0
    total_deployments = 0

    for service_name, regions in deployment_results.items():
        for region, deployments in regions.items():
            for deployment in deployments:
                total_deployments += 1
                if deployment['state'] in ['running', 'scheduled', 'waiting', 'blocked']:
                    active_deployments += 1
                    print(f"  🏃 ACTIVE: {service_name} → {deployment['host']} ({region}): {deployment['state']}")

    print(f"📊 Deployment status: {active_deployments} active out of {total_deployments} total")

    # If we still have active deployments, keep monitoring regardless of rollback steps
    if active_deployments > 0:
        print(f"🔄 Still have {active_deployments} active deployments - continuing to monitor...")
        return False, f"Deployments still running ({active_deployments} active)"

    # Check for rollback/redeploy block steps ONLY if all deployments are done
    rollback_jobs = []
    blocked_jobs = []

    for job in build_data.get('jobs', []):
        job_type = job.get('type', '')
        job_state = job.get('state', '')
        job_name = job.get('name', '')
        job_id = job.get('id', 'unknown')

        # DEBUG: Log all job states for analysis
        print(f"Job '{job_name}' (ID: {job_id[:8]}): type={job_type}, state={job_state}")

        # Look for any blocked/waiting jobs (could indicate manual intervention needed)
        if job_state in ['blocked', 'waiting']:
            blocked_jobs.append({'name': job_name, 'type': job_type, 'state': job_state})

        # Look for rollback/redeploy related jobs
        job_name_lower = job_name.lower()
        if ('rollback' in job_name_lower or 'redeploy' in job_name_lower):
            rollback_jobs.append({'name': job_name, 'type': job_type, 'state': job_state})

    # Debug output
    if rollback_jobs:
        print(f"Found {len(rollback_jobs)} rollback-related jobs:")
        for job in rollback_jobs:
            print(f"  - {job['name']} ({job['type']}, {job['state']})")

    if blocked_jobs:
        print(f"Found {len(blocked_jobs)} blocked/waiting jobs:")
        for job in blocked_jobs:
            print(f"  - {job['name']} ({job['type']}, {job['state']})")

    # NOW check for rollback decision points - but only if no deployments are active
    for job in rollback_jobs:
        if (job['state'] in ['blocked', 'waiting'] and
            'rollback' in job['name'].lower() and
            'redeploy' in job['name'].lower()):
            print(f"  🛑 All deployments complete AND rollback decision reached: {job['name']} ({job['state']})")
            return True, f"Deployments complete - rollback decision point: {job['name']} ({job['state']})"

    # Check for other manual intervention jobs (waiter type that are blocked)
    for job in blocked_jobs:
        if job['type'] == 'waiter' and job['state'] in ['blocked', 'waiting']:
            # But only stop if it's NOT a deployment-related job and all deployments are done
            job_name_lower = job['name'].lower()
            if not any(keyword in job_name_lower for keyword in ['deploy', 'version', 'region']):
                print(f"  🛑 All deployments complete AND manual intervention needed: {job['name']} ({job['state']})")
                return True, f"Deployments complete - manual intervention needed: {job['name']} ({job['state']})"

    # If we get here, deployments are done but no clear decision point
    if total_deployments > 0:
        print("✅ All deployments complete but no clear stop condition - continuing to monitor briefly...")
        return False, "All deployments complete, monitoring for decision points..."

    # No deployments found yet
    print("⏰ No deployments detected yet, continuing to monitor...")
    return False, "No deployments detected yet"


def get_pipeline_progress(build_data, deployment_results):
    """
    Calculate overall pipeline progress for the live dashboard.
    FIXED: Only counts actual deployment-related jobs, not all script jobs

    Returns:
        dict: Progress statistics including completion percentage
    """
    # Count deployment jobs from our parsed results instead of all script jobs
    total_deployment_jobs = 0
    completed_deployment_jobs = 0
    running_deployment_jobs = 0
    failed_deployment_jobs = 0

    print(f"\n=== DEBUG: Pipeline Progress Calculation (FIXED) ===")

    # Count actual deployment jobs (not all script jobs like rollback, summary, etc.)
    for service_name, regions in deployment_results.items():
        for region, deployments in regions.items():
            for deployment in deployments:
                total_deployment_jobs += 1

                if deployment['state'] in ['passed', 'failed', 'canceled', 'skipped']:
                    completed_deployment_jobs += 1
                    if deployment['state'] == 'failed':
                        failed_deployment_jobs += 1
                elif deployment['state'] == 'running':
                    running_deployment_jobs += 1

                print(f"  Deployment job: {service_name} → {deployment['host']} ({region}): {deployment['state']}")

    # Calculate progress based on actual deployment jobs
    progress_percent = (completed_deployment_jobs / total_deployment_jobs * 100) if total_deployment_jobs > 0 else 0

    print(f"DEPLOYMENT Progress: {completed_deployment_jobs}/{total_deployment_jobs} = {progress_percent:.1f}%")
    print(f"Running deployments: {running_deployment_jobs}")
    print(f"Failed deployments: {failed_deployment_jobs}")

    return {
        'total_jobs': total_deployment_jobs,
        'completed_jobs': completed_deployment_jobs,
        'running_jobs': running_deployment_jobs,
        'failed_jobs': failed_deployment_jobs,
        'progress_percent': progress_percent,
        'remaining_jobs': total_deployment_jobs - completed_deployment_jobs
    }


def parse_deployment_jobs(build_data):
    """
    Parse build jobs to extract deployment information.
    Groups jobs by service, region, and host for comprehensive analysis.

    Returns:
        dict: Organized deployment results by service and region
    """
    deployment_results = defaultdict(lambda: defaultdict(list))
    post_script_results = defaultdict(lambda: defaultdict(list))

    # Job state mappings for better readability
    state_emoji = {
        'passed': '✅',
        'failed': '❌',
        'running': '🏃',
        'scheduled': '⏰',
        'canceled': '⏹️',
        'skipped': '⏭️',
        'blocked': '🚫',
        'unblocked': '🔓',
        'waiting': '⏸️'
    }

    print(f"\n=== DEBUG: Parsing Deployment Jobs ===")

    for job in build_data.get('jobs', []):
        job_name = job.get('name', 'Unknown Job')
        job_state = job.get('state', 'unknown')
        job_type = job.get('type', 'unknown')

        # Skip non-command jobs (like input, wait, etc.)
        if job_type != 'script':
            continue

        # Parse deployment jobs using regex patterns that account for emoji prefixes
        deploy_pattern = r':windows:\s+Deploy\s+([a-zA-Z0-9-_]+(?:\s+[a-zA-Z0-9-_]+)*)\s+([\d\w.-]+)\s+to\s+(\w+)'
        script_pattern = r':(gear|pwsh):\s+Run\s+([\w.-]+)\s+for\s+([a-zA-Z0-9-_]+(?:\s+[a-zA-Z0-9-_]+)*)\s+on\s+(\w+)'

        deploy_match = re.search(deploy_pattern, job_name)
        script_match = re.search(script_pattern, job_name)

        print(f"  Testing job: '{job_name}' (state: {job_state})")

        if deploy_match:
            service_name = deploy_match.group(1)
            version = deploy_match.group(2)
            host = deploy_match.group(3)

            # Determine region from job grouping or fallback to parsing
            region = extract_region_from_job(job, build_data)

            print(f"    ✅ DEPLOYMENT: {service_name} v{version} → {host} ({region}) [{job_state}]")

            deployment_results[service_name][region].append({
                'host': host,
                'version': version,
                'state': job_state,
                'emoji': state_emoji.get(job_state, '❓'),
                'job_id': job.get('id', 'unknown'),
                'started_at': job.get('started_at'),
                'finished_at': job.get('finished_at'),
                'exit_status': job.get('exit_status'),
                'web_url': job.get('web_url', '')
            })

        elif script_match:
            script_name = script_match.group(1)
            service_name = script_match.group(2)
            host = script_match.group(3)

            region = extract_region_from_job(job, build_data)

            print(f"    🔧 POST-SCRIPT: {script_name} for {service_name} on {host} ({region}) [{job_state}]")

            post_script_results[service_name][region].append({
                'host': host,
                'script': script_name,
                'state': job_state,
                'emoji': state_emoji.get(job_state, '❓'),
                'job_id': job.get('id', 'unknown'),
                'exit_status': job.get('exit_status'),
                'web_url': job.get('web_url', '')
            })
        else:
            print(f"    ⚠️ UNMATCHED: Skipping non-deployment script job")

    print(f"Found {sum(len(regions) for regions in deployment_results.values())} deployment regions")
    print(f"Found {sum(len(regions) for regions in post_script_results.values())} post-script regions")

    return deployment_results, post_script_results


def extract_region_from_job(job, build_data):
    """
    Extract region information from job context.
    Enhanced with comprehensive debug output to troubleshoot region detection.
    """
    job_name = job.get('name', 'Unknown Job')
    job_step_key = job.get('step_key')
    job_id = job.get('id', 'unknown')[:8]

    print(f"\n    🔍 DEBUG: Extracting region for job '{job_name}' (ID: {job_id})")
    print(f"        Step key: {job_step_key}")
    print(f"        Job type: {job.get('type')}")

    # Method 1: Try to find region from step key
    if job_step_key and isinstance(job_step_key, str):
        print(f"        Searching step key: '{job_step_key}'")
        region_match = re.search(r'([a-z]+-[a-z]+-\d+)', job_step_key)
        if region_match:
            region = region_match.group(1)
            print(f"        ✅ Found region in step key: {region}")
            return region
        else:
            print(f"        ❌ No region pattern found in step key")
    else:
        print(f"        ⚠️ No step key available")

    # Method 2: Look for region in job group structure
    # Check if job has a step property that might contain group info
    job_step = job.get('step', {})
    if job_step:
        print(f"        Job step data: {job_step}")

    # Method 3: Try to find region from step groups in build data
    print(f"        Checking build data for step groups...")
    steps_found = 0
    for step in build_data.get('steps', []):
        steps_found += 1
        step_type = step.get('type', 'unknown')
        step_label = step.get('label', '')
        step_key = step.get('key', '')

        print(f"        Step #{steps_found}: type={step_type}, label='{step_label}', key='{step_key}'")

        if step_type == 'group' and 'Region' in step_label:
            region_match = re.search(r'Region\s+([a-z]+-[a-z]+-\d+)', step_label)
            if region_match:
                region = region_match.group(1)
                print(f"        ✅ Found region in group label: {region}")
                return region

    if steps_found == 0:
        print(f"        ⚠️ No steps found in build data")

    # Method 4: Try to extract region from job name itself
    print(f"        Searching job name for region patterns: '{job_name}'")
    region_match = re.search(r'([a-z]+-[a-z]+-\d+)', job_name.lower())
    if region_match:
        region = region_match.group(1)
        print(f"        ✅ Found region in job name: {region}")
        return region
    else:
        print(f"        ❌ No region pattern found in job name")

    # Method 5: Check if there's any metadata or environment info
    job_env = job.get('env', {})
    if job_env:
        print(f"        Job env data: {job_env}")

    # Last resort: check build metadata for region info
    build_meta = build_data.get('meta_data', {})
    if build_meta:
        print(f"        Build metadata keys: {list(build_meta.keys())}")
        # Look for any region-related metadata
        for key, value in build_meta.items():
            if 'region' in key.lower():
                print(f"        Found region metadata: {key} = {value}")

    print(f"        ❌ FALLBACK: Using 'unknown-region'")
    return 'unknown-region'


def calculate_deployment_statistics(deployment_results, post_script_results):
    """
    Calculate comprehensive deployment statistics for the summary.

    Returns:
        dict: Statistics including success rates, failure counts, etc.
    """
    stats = {
        'total_services': len(deployment_results),
        'total_deployments': 0,
        'successful_deployments': 0,
        'failed_deployments': 0,
        'running_deployments': 0,
        'pending_deployments': 0,
        'total_post_scripts': 0,
        'successful_post_scripts': 0,
        'failed_post_scripts': 0,
        'running_post_scripts': 0,
        'regions': set(),
        'hosts': set(),
        'services_by_status': defaultdict(int)
    }

    # Analyze deployment results
    for service_name, regions in deployment_results.items():
        service_success = True
        service_has_failures = False
        service_has_running = False

        for region, deployments in regions.items():
            stats['regions'].add(region)
            for deployment in deployments:
                stats['total_deployments'] += 1
                stats['hosts'].add(deployment['host'])

                if deployment['state'] == 'passed':
                    stats['successful_deployments'] += 1
                elif deployment['state'] == 'failed':
                    stats['failed_deployments'] += 1
                    service_has_failures = True
                    service_success = False
                elif deployment['state'] == 'running':
                    stats['running_deployments'] += 1
                    service_has_running = True
                    service_success = False
                elif deployment['state'] in ['scheduled', 'waiting']:
                    stats['pending_deployments'] += 1
                    service_success = False

        # Categorize service status
        if service_success:
            stats['services_by_status']['completed'] += 1
        elif service_has_failures:
            stats['services_by_status']['failed'] += 1
        elif service_has_running:
            stats['services_by_status']['running'] += 1
        else:
            stats['services_by_status']['pending'] += 1

    # Analyze post-script results
    for service_name, regions in post_script_results.items():
        for region, scripts in regions.items():
            for script in scripts:
                stats['total_post_scripts'] += 1
                if script['state'] == 'passed':
                    stats['successful_post_scripts'] += 1
                elif script['state'] == 'failed':
                    stats['failed_post_scripts'] += 1
                elif script['state'] == 'running':
                    stats['running_post_scripts'] += 1

    # Convert sets to counts
    stats['total_regions'] = len(stats['regions'])
    stats['total_hosts'] = len(stats['hosts'])

    return stats


def generate_live_summary_markdown(deployment_results, post_script_results, stats, metadata, progress, update_count, start_time):
    """
    Generate a live-updating markdown summary of the deployment.
    This is the main "live dashboard" that gets updated every 10 seconds.
    """
    current_time = datetime.now()
    elapsed_time = current_time - start_time
    timestamp = current_time.strftime("%Y-%m-%d %H:%M:%S UTC")

    # Calculate success rate
    if stats['total_deployments'] > 0:
        success_rate = (stats['successful_deployments'] / stats['total_deployments']) * 100
    else:
        success_rate = 0

    # Dynamic status based on current state
    if stats['running_deployments'] > 0 or stats['pending_deployments'] > 0:
        status_emoji = "🚀"
        status_text = "DEPLOYING"
    elif success_rate >= 95 and stats['failed_deployments'] == 0:
        status_emoji = "🎉"
        status_text = "SUCCESS"
    elif success_rate >= 80:
        status_emoji = "✅"
        status_text = "MOSTLY SUCCESS"
    elif success_rate >= 60:
        status_emoji = "⚠️"
        status_text = "PARTIAL SUCCESS"
    else:
        status_emoji = "❌"
        status_text = "CRITICAL ISSUES"

    markdown = f"""
# {status_emoji} Live Deployment Dashboard - {status_text}

🔄 **Live Update #{update_count}** | **Last Updated:** {timestamp} | **Runtime:** {str(elapsed_time).split('.')[0]}

---

## 📊 Real-Time Progress

**Overall Progress:** {progress['progress_percent']:.1f}% ({progress['completed_jobs']}/{progress['total_jobs']} deployment jobs complete)

| Status | Count | Percentage |
|--------|--------|------------|
| ✅ Successful | {stats['successful_deployments']} | {(stats['successful_deployments']/stats['total_deployments']*100) if stats['total_deployments'] > 0 else 0:.1f}% |
| 🏃 Running | {stats['running_deployments']} | {(stats['running_deployments']/stats['total_deployments']*100) if stats['total_deployments'] > 0 else 0:.1f}% |
| ⏰ Pending | {stats['pending_deployments']} | {(stats['pending_deployments']/stats['total_deployments']*100) if stats['total_deployments'] > 0 else 0:.1f}% |
| ❌ Failed | {stats['failed_deployments']} | {(stats['failed_deployments']/stats['total_deployments']*100) if stats['total_deployments'] > 0 else 0:.1f}% |

**Deployment Targets:** {stats['total_services']} services → {stats['total_regions']} regions → {stats['total_hosts']} hosts

---

## 🚀 Service Status Matrix
"""

    # Service-by-service live status
    for service_name, regions in sorted(deployment_results.items()):
        service_total = 0
        service_success = 0
        service_running = 0
        service_failed = 0
        service_pending = 0

        # Count totals for this service
        for region, deployments in regions.items():
            for deployment in deployments:
                service_total += 1
                if deployment['state'] == 'passed':
                    service_success += 1
                elif deployment['state'] == 'running':
                    service_running += 1
                elif deployment['state'] == 'failed':
                    service_failed += 1
                elif deployment['state'] in ['scheduled', 'waiting']:
                    service_pending += 1

        # Dynamic service emoji based on current state
        if service_running > 0:
            service_emoji = "🏃"
            service_status = "DEPLOYING"
        elif service_failed > 0:
            service_emoji = "❌"
            service_status = "HAS FAILURES"
        elif service_pending > 0:
            service_emoji = "⏰"
            service_status = "PENDING"
        elif service_success == service_total:
            service_emoji = "✅"
            service_status = "COMPLETE"
        else:
            service_emoji = "❓"
            service_status = "UNKNOWN"

        markdown += f"\n### {service_emoji} {service_name} - {service_status}\n"

        if service_total > 0:
            completion = (service_success / service_total * 100)
            markdown += f"**Progress:** {completion:.0f}% ({service_success}/{service_total}) "

            if service_running > 0:
                markdown += f"| 🏃 {service_running} deploying "
            if service_failed > 0:
                markdown += f"| ❌ {service_failed} failed "
            if service_pending > 0:
                markdown += f"| ⏰ {service_pending} pending"

            markdown += "\n\n"

        # Live region breakdown for this service
        for region, deployments in sorted(regions.items()):
            if deployments:
                version = deployments[0]['version']  # All deployments should be same version
                markdown += f"**{region.upper()}** (v{version}): "

                # Group by status for cleaner display with live indicators
                status_groups = defaultdict(list)
                for deployment in deployments:
                    status_groups[deployment['state']].append(deployment['host'])

                status_parts = []
                for state, hosts in status_groups.items():
                    if state == 'passed':
                        emoji = '✅'
                    elif state == 'failed':
                        emoji = '❌'
                    elif state == 'running':
                        emoji = '🏃'
                    elif state in ['scheduled', 'waiting']:
                        emoji = '⏰'
                    else:
                        emoji = '❓'

                    status_parts.append(f"{emoji} {', '.join(hosts)}")

                markdown += " | ".join(status_parts) + "\n\n"

    # Current failures section (if any)
    current_failures = []
    for service_name, regions in deployment_results.items():
        for region, deployments in regions.items():
            for deployment in deployments:
                if deployment['state'] == 'failed':
                    current_failures.append({
                        'service': service_name,
                        'region': region,
                        'host': deployment['host'],
                        'version': deployment['version'],
                        'exit_status': deployment.get('exit_status', 'unknown'),
                        'web_url': deployment.get('web_url', '')
                    })

    if current_failures:
        markdown += "\n## ❌ Current Failures\n\n"
        markdown += "| Service | Region | Host | Version | Exit Code |\n"
        markdown += "|---------|--------|------|---------|----------|\n"

        for failure in current_failures:
            markdown += f"| {failure['service']} | {failure['region']} | {failure['host']} | {failure['version']} | {failure['exit_status']} |\n"

    # Running jobs section
    running_jobs = []
    for service_name, regions in deployment_results.items():
        for region, deployments in regions.items():
            for deployment in deployments:
                if deployment['state'] == 'running':
                    running_jobs.append({
                        'service': service_name,
                        'region': region,
                        'host': deployment['host'],
                        'version': deployment['version']
                    })

    if running_jobs:
        markdown += f"\n## 🏃 Currently Deploying ({len(running_jobs)} active)\n\n"
        for job in running_jobs:
            markdown += f"- **{job['service']}** v{job['version']} → {job['host']} ({job['region']})\n"

    # Post-script summary (if any)
    if post_script_results and stats['total_post_scripts'] > 0:
        markdown += f"\n## 🔧 Post-Deployment Scripts\n\n"
        script_success_rate = (stats['successful_post_scripts'] / stats['total_post_scripts'] * 100) if stats['total_post_scripts'] > 0 else 0
        markdown += f"**Success Rate:** {script_success_rate:.1f}% ({stats['successful_post_scripts']}/{stats['total_post_scripts']})"

        if stats['running_post_scripts'] > 0:
            markdown += f" | 🏃 {stats['running_post_scripts']} running"

        markdown += "\n\n"

    # Footer with metadata
    if metadata:
        generation_time = metadata.get('generation-timestamp', 'unknown')
        markdown += f"\n---\n\n*Pipeline generated: {generation_time} | Next update in 10 seconds...*\n"
    else:
        markdown += f"\n---\n\n*Next update in 10 seconds...*\n"

    return markdown


def create_buildkite_annotation(markdown_content, is_final=False, local_mode=False):
    """
    Create or update a Buildkite annotation with the deployment summary.
    Uses consistent context so updates replace previous annotations.

    Args:
        markdown_content: The markdown content to annotate
        is_final: Whether this is the final annotation
        local_mode: If True, write to local file instead of creating annotation
    """
    if local_mode:
        # Local testing mode - write to SUMMARY.md file
        output_file = "SUMMARY.md"
        with open(output_file, 'w') as f:
            f.write(markdown_content)
        print(f"📄 Local mode: Summary written to {output_file}")
        return True

    annotation_style = "info" if not is_final else "success"

    if getenv("BUILDKITE_COMPUTE_TYPE") is not None:
        # Write markdown to temporary file
        temp_file = "live_deployment_summary.md"
        with open(temp_file, 'w') as f:
            f.write(markdown_content)

        # Create/update annotation with consistent context for replacement
        annotate_cmd = f'buildkite-agent annotate --style {annotation_style} --context live-deployment-dashboard < {temp_file}'
        result = system(annotate_cmd)

        return result == 0
    else:
        print("=" * 80)
        print(markdown_content)
        print("=" * 80)
        return True


def parse_args():
    """Parse command line arguments for local testing support"""
    parser = argparse.ArgumentParser(
        description='Generate live deployment dashboard annotation',
        epilog='''
Examples:
  # Production mode (in Buildkite environment):
  python generate_annotation_summary.py

  # Local testing mode:
  export BUILDKITE_API_TOKEN=bkua_xxxxx
  python generate_annotation_summary.py --build-id 12345 --org demo --pipeline my-pipeline
        ''',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument(
        '--build-id',
        help='Build ID to analyze (enables local testing mode)'
    )
    parser.add_argument(
        '--org',
        help='Buildkite organization name (required for local testing)',
        default='demo'
    )
    parser.add_argument(
        '--pipeline',
        help='Pipeline name (required for local testing)'
    )
    parser.add_argument(
        '--no-loop',
        action='store_true',
        help='Generate single summary and exit (useful for testing)'
    )

    return parser.parse_args()


def main():
    """
    Main function that runs the live deployment monitoring loop.
    Updates the annotation every 10 seconds until pipeline reaches terminal state.
    """
    args = parse_args()

    # Determine if we're in local testing mode
    local_mode = bool(args.build_id)

    if local_mode:
        if not args.pipeline:
            print("❌ --pipeline is required when using --build-id for local testing")
            return
        print(f"=== Starting Local Testing Mode ===")
        print(f"🔧 Build ID: {args.build_id}")
        print(f"🔧 Organization: {args.org}")
        print(f"🔧 Pipeline: {args.pipeline}")
        print(f"📄 Output will be written to SUMMARY.md")
    else:
        print("=== Starting Live Deployment Dashboard v10 ===")
        print("🔧 FIXED: Progress calculation now only counts deployment jobs, not all script jobs")

    update_count = 0
    start_time = datetime.now()

    # Initial metadata load (skip in local mode since artifacts won't be available)
    metadata = None if local_mode else get_metadata_artifact()

    if not local_mode:
        print("🚀 Beginning live monitoring loop (updates every 10 seconds)")
        print("📊 Will stop when pipeline reaches rollback decision point or completes")

    while True:
        update_count += 1
        if local_mode:
            print(f"\n--- Generating Summary for Build {args.build_id} ---")
        else:
            print(f"\n--- Live Update #{update_count} at {datetime.now().strftime('%H:%M:%S')} ---")

        # Get current build data
        if local_mode:
            build_data = get_current_build_data(args.build_id, args.org, args.pipeline)
        else:
            build_data = get_current_build_data()

        if not build_data:
            if local_mode:
                print("❌ Failed to fetch build data - check build ID, org, and pipeline name")
                return
            else:
                print("❌ Failed to fetch build data, retrying in 10 seconds...")
                time.sleep(10)
                continue

        # Parse current deployment state FIRST (always get the latest data)
        deployment_results, post_script_results = parse_deployment_jobs(build_data)
        stats = calculate_deployment_statistics(deployment_results, post_script_results)

        # FIXED: Pass deployment_results to progress calculation so it only counts actual deployments
        progress = get_pipeline_progress(build_data, deployment_results)

        # FIXED: Check if we should stop monitoring AFTER collecting data AND pass deployment_results
        should_stop, stop_reason = should_stop_monitoring(build_data, deployment_results)


        if should_stop and not local_mode:
            print(f"🛑 Detected stop condition: {stop_reason}")
            print("📊 Generating final comprehensive summary with latest deployment data...")

            # Create final annotation with the freshly collected data
            final_markdown = generate_live_summary_markdown(
                deployment_results, post_script_results, stats, metadata, progress, update_count, start_time
            ).replace("*Next update in 10 seconds...*", f"*Final summary - {stop_reason}*")

            create_buildkite_annotation(final_markdown, is_final=True, local_mode=local_mode)
            print("✅ Final deployment summary created with complete deployment status!")
            break

        # Continue with regular live updates if not stopping
        if not deployment_results and update_count == 1 and not local_mode:
            print("⏰ No deployment jobs detected yet, waiting for pipeline to start...")
            create_buildkite_annotation(f"""
# ⏰ Live Deployment Dashboard - WAITING

🔄 **Live Update #{update_count}** | **Waiting for deployments to begin...**

The deployment pipeline is starting up. Deployment jobs will appear here as they begin executing.

*Next update in 10 seconds...*
""", is_final=False, local_mode=local_mode)
        else:
            # Generate live summary for regular updates using data we already collected
            markdown_summary = generate_live_summary_markdown(
                deployment_results, post_script_results, stats, metadata, progress, update_count, start_time
            )

            # In local mode, remove the "next update" footer
            if local_mode:
                markdown_summary = markdown_summary.replace("*Next update in 10 seconds...*", f"*Generated at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} for build {args.build_id}*")

            # Update annotation
            success = create_buildkite_annotation(markdown_summary, is_final=False, local_mode=local_mode)

            if success:
                print(f"✅ {'Generated summary' if local_mode else 'Updated live dashboard'} (Progress: {progress['progress_percent']:.1f}%)")
                if stats['failed_deployments'] > 0:
                    print(f"⚠️  {stats['failed_deployments']} failed deployments detected")
                if stats['running_deployments'] > 0:
                    print(f"🏃 {stats['running_deployments']} deployments currently running")
            else:
                print("❌ Failed to update annotation")

        # Exit after one iteration in local mode or if --no-loop specified
        if local_mode or args.no_loop:
            print(f"📄 Local testing complete - summary {'written to SUMMARY.md' if local_mode else 'generated'}")
            break

        # Wait 10 seconds before next update (production mode only)
        print("⏰ Waiting 10 seconds for next update...")
        time.sleep(10)

    total_runtime = datetime.now() - start_time
    print(f"\n=== {'Local Testing' if local_mode else 'Live Dashboard'} Complete ===")
    print(f"📊 Total updates: {update_count}")
    print(f"⏱️  Total runtime: {str(total_runtime).split('.')[0]}")
    print("🎯 Dashboard {'testing' if local_mode else 'monitoring'} finished!")


if __name__ == "__main__":
    main()
