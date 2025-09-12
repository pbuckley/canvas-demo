#!/usr/bin/env python

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
    else:
        print("Running locally, fetching bk api token from env var BK_API_TOKEN")
        return getenv("BK_API_TOKEN")


def get_current_build_data():
    """
    Get the current build data from Buildkite API to analyze deployment results.
    Returns build data with all job information.
    """
    org_name = getenv("BUILDKITE_ORGANIZATION_SLUG")
    pipeline_name = getenv("BUILDKITE_PIPELINE_SLUG")
    build_number = getenv("BUILDKITE_BUILD_NUMBER")

    if not all([org_name, pipeline_name, build_number]):
        print("Missing required environment variables for API call")
        return None

    constructed_url = f"https://api.buildkite.com/v2/organizations/{org_name}/pipelines/{pipeline_name}/builds/{build_number}"
    api_token = fetch_bk_api_token()
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


def should_stop_monitoring(build_data):
    """
    Determine if we should stop live monitoring based on pipeline state.
    Stops when we hit the rollback block step or pipeline is finished/failed.

    Returns:
        tuple: (should_stop: bool, reason: str)
    """
    build_state = build_data.get('state', 'unknown')

    print(f"\n=== DEBUG: Stop Monitoring Check ===")
    print(f"Build state: {build_state}")

    # Stop if build is in terminal state
    if build_state in ['passed', 'failed', 'canceled']:
        return True, f"Build finished with state: {build_state}"

    # Check all jobs for rollback/redeploy block step
    rollback_jobs = []
    blocked_jobs = []

    for job in build_data.get('jobs', []):
        job_type = job.get('type', '')
        job_state = job.get('state', '')
        job_name = job.get('name', '')
        job_id = job.get('id', 'unknown')

        # DEBUG: Log all job states for analysis
        print(f"Job '{job_name}' (ID: {job_id}): type={job_type}, state={job_state}")

        # Look for any blocked/waiting jobs (could indicate manual intervention needed)
        if job_state in ['blocked', 'waiting']:
            blocked_jobs.append({'name': job_name, 'type': job_type, 'state': job_state})

        # Look for rollback/redeploy related jobs
        job_name_lower = job_name.lower()
        if ('rollback' in job_name_lower or 'redeploy' in job_name_lower):
            rollback_jobs.append({'name': job_name, 'type': job_type, 'state': job_state})

        # Check for the specific block step pattern from generate_deploy_targets.py
        # Looking for jobs with "Rollback / Redeploy" in the name
        if job_type == 'waiter' and ('rollback' in job_name_lower and 'redeploy' in job_name_lower):
            print(f"  Found rollback block step: {job_name} (state: {job_state})")
            if job_state in ['blocked', 'waiting', 'unblocked']:
                return True, f"Reached rollback decision point: {job_name} ({job_state})"

    # Debug output
    if rollback_jobs:
        print(f"Found {len(rollback_jobs)} rollback-related jobs:")
        for job in rollback_jobs:
            print(f"  - {job['name']} ({job['type']}, {job['state']})")

    if blocked_jobs:
        print(f"Found {len(blocked_jobs)} blocked/waiting jobs:")
        for job in blocked_jobs:
            print(f"  - {job['name']} ({job['type']}, {job['state']})")

        # If we have any blocked jobs that might be manual intervention, stop
        for job in blocked_jobs:
            if job['type'] == 'waiter':
                return True, f"Manual intervention needed: {job['name']} ({job['state']})"

    # Continue monitoring if pipeline is still active
    print("Pipeline still running, continuing monitoring...")
    return False, "Pipeline still running"


def get_pipeline_progress(build_data):
    """
    Calculate overall pipeline progress for the live dashboard.

    Returns:
        dict: Progress statistics including completion percentage
    """
    total_jobs = 0
    completed_jobs = 0
    running_jobs = 0
    failed_jobs = 0

    print(f"\n=== DEBUG: Pipeline Progress Calculation ===")

    for job in build_data.get('jobs', []):
        job_name = job.get('name', 'Unknown Job')
        job_state = job.get('state', 'unknown')
        job_type = job.get('type', 'unknown')
        job_id = job.get('id', 'unknown')

        # Only count script jobs (actual deployment work)
        if job.get('type') == 'script':
            total_jobs += 1

            print(f"Script job '{job_name}' (ID: {job_id}): state={job_state}")

            if job_state in ['passed', 'failed', 'canceled', 'skipped']:
                completed_jobs += 1
                if job_state == 'failed':
                    failed_jobs += 1
            elif job_state == 'running':
                running_jobs += 1

    progress_percent = (completed_jobs / total_jobs * 100) if total_jobs > 0 else 0

    print(f"Pipeline progress: {completed_jobs}/{total_jobs} = {progress_percent:.1f}%")
    print(f"Running jobs: {running_jobs}")
    print(f"Failed jobs: {failed_jobs}")

    return {
        'total_jobs': total_jobs,
        'completed_jobs': completed_jobs,
        'running_jobs': running_jobs,
        'failed_jobs': failed_jobs,
        'progress_percent': progress_percent,
        'remaining_jobs': total_jobs - completed_jobs
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

    for job in build_data.get('jobs', []):
        job_name = job.get('name', 'Unknown Job')
        job_state = job.get('state', 'unknown')
        job_type = job.get('type', 'unknown')

        # Skip non-command jobs (like input, wait, etc.)
        if job_type != 'script':
            continue

        # Parse deployment jobs using regex patterns
        deploy_pattern = r':windows:\s+Deploy\s+([a-zA-Z0-9-_]+(?:\s+[a-zA-Z0-9-_]+)*)\s+([\d\w.-]+)\s+to\s+(\w+)'
        script_pattern = r':gear:\s+Run\s+([\w.-]+)\s+for\s+([a-zA-Z0-9-_]+(?:\s+[a-zA-Z0-9-_]+)*)\s+on\s+(\w+)'

        deploy_match = re.search(deploy_pattern, job_name)
        script_match = re.search(script_pattern, job_name)

        # DEBUG: Show pattern matching attempts
        print(f"  Testing patterns on: '{job_name}'")
        print(f"    Deploy pattern: {deploy_pattern}")
        print(f"    Script pattern: {script_pattern}")
        print(f"    Deploy match: {bool(deploy_match)}")
        print(f"    Script match: {bool(script_match)}")

        if deploy_match:
            service_name = deploy_match.group(1)
            version = deploy_match.group(2)
            host = deploy_match.group(3)

            # Determine region from job grouping or fallback to parsing
            region = extract_region_from_job(job, build_data)

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

            post_script_results[service_name][region].append({
                'host': host,
                'script': script_name,
                'state': job_state,
                'emoji': state_emoji.get(job_state, '❓'),
                'job_id': job.get('id', 'unknown'),
                'exit_status': job.get('exit_status'),
                'web_url': job.get('web_url', '')
            })

    return deployment_results, post_script_results


def extract_region_from_job(job, build_data):
    """
    Extract region information from job context.
    Looks for region information in job groups or step keys.
    """
    # Try to find region from step group
    for step in build_data.get('steps', []):
        if step.get('type') == 'group':
            group_label = step.get('label', '')
            if 'Region' in group_label:
                region_match = re.search(r'Region\s+([a-z]+-[a-z]+-\d+)', group_label)
                if region_match:
                    return region_match.group(1)

    # Fallback to parsing from job name or return default
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

**Overall Progress:** {progress['progress_percent']:.1f}% ({progress['completed_jobs']}/{progress['total_jobs']} jobs complete)

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


def create_buildkite_annotation(markdown_content, is_final=False):
    """
    Create or update a Buildkite annotation with the deployment summary.
    Uses consistent context so updates replace previous annotations.
    """
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


def main():
    """
    Main function that runs the live deployment monitoring loop.
    Updates the annotation every 10 seconds until pipeline reaches terminal state.
    """
    print("=== Starting Live Deployment Dashboard ===")

    update_count = 0
    start_time = datetime.now()

    # Initial metadata load
    metadata = get_metadata_artifact()

    print("🚀 Beginning live monitoring loop (updates every 10 seconds)")
    print("📊 Will stop when pipeline reaches rollback decision point or completes")

    while True:
        update_count += 1
        print(f"\n--- Live Update #{update_count} at {datetime.now().strftime('%H:%M:%S')} ---")

        # Get current build data
        build_data = get_current_build_data()
        if not build_data:
            print("❌ Failed to fetch build data, retrying in 10 seconds...")
            time.sleep(10)
            continue

        # Check if we should stop monitoring
        should_stop, stop_reason = should_stop_monitoring(build_data)
        if should_stop:
            print(f"🛑 Stopping live updates: {stop_reason}")

            # Generate final summary
            deployment_results, post_script_results = parse_deployment_jobs(build_data)
            stats = calculate_deployment_statistics(deployment_results, post_script_results)
            progress = get_pipeline_progress(build_data)

            # Create final annotation (without "Next update in 10 seconds...")
            final_markdown = generate_live_summary_markdown(
                deployment_results, post_script_results, stats, metadata, progress, update_count, start_time
            ).replace("*Next update in 10 seconds...*", f"*Final summary - {stop_reason}*")

            create_buildkite_annotation(final_markdown, is_final=True)
            print("✅ Final deployment summary created!")
            break

        # Parse current deployment state
        deployment_results, post_script_results = parse_deployment_jobs(build_data)

        if not deployment_results and update_count == 1:
            print("⏰ No deployment jobs detected yet, waiting for pipeline to start...")
            create_buildkite_annotation(f"""
# ⏰ Live Deployment Dashboard - WAITING

🔄 **Live Update #{update_count}** | **Waiting for deployments to begin...**

The deployment pipeline is starting up. Deployment jobs will appear here as they begin executing.

*Next update in 10 seconds...*
""")
        else:
            # Calculate statistics and progress
            stats = calculate_deployment_statistics(deployment_results, post_script_results)
            progress = get_pipeline_progress(build_data)

            # Generate live summary
            markdown_summary = generate_live_summary_markdown(
                deployment_results, post_script_results, stats, metadata, progress, update_count, start_time
            )

            # Update annotation
            success = create_buildkite_annotation(markdown_summary)

            if success:
                print(f"✅ Updated live dashboard (Progress: {progress['progress_percent']:.1f}%)")
                if stats['failed_deployments'] > 0:
                    print(f"⚠️  {stats['failed_deployments']} failed deployments detected")
                if stats['running_deployments'] > 0:
                    print(f"🏃 {stats['running_deployments']} deployments currently running")
            else:
                print("❌ Failed to update annotation")

        # Wait 10 seconds before next update
        print("⏰ Waiting 10 seconds for next update...")
        time.sleep(10)

    total_runtime = datetime.now() - start_time
    print(f"\n=== Live Dashboard Complete ===")
    print(f"📊 Total updates: {update_count}")
    print(f"⏱️  Total runtime: {str(total_runtime).split('.')[0]}")
    print("🎯 Dashboard monitoring finished!")


if __name__ == "__main__":
    main()
