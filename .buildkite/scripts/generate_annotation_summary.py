#!/usr/bin/env python

from os import getenv, popen, system
from datetime import datetime
import json
import requests
import re
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

    print(f"Fetching build data from: {constructed_url}")

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
        'unblocked': '🔓'
    }

    for job in build_data.get('jobs', []):
        job_name = job.get('name', 'Unknown Job')
        job_state = job.get('state', 'unknown')
        job_type = job.get('type', 'unknown')

        # Skip non-command jobs (like input, wait, etc.)
        if job_type != 'script':
            continue

        # Parse deployment jobs using regex patterns
        deploy_pattern = r'Deploy (\w+(?:\s+\w+)*) ([\d\w.-]+) to (\w+)'
        script_pattern = r'Run ([\w.-]+) for (\w+(?:\s+\w+)*) on (\w+)'

        deploy_match = re.search(deploy_pattern, job_name)
        script_match = re.search(script_pattern, job_name)

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
                'exit_status': job.get('exit_status')
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
                'exit_status': job.get('exit_status')
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
                region_match = re.search(r'Region (\w+-\w+-\d+)', group_label)
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
        'total_post_scripts': 0,
        'successful_post_scripts': 0,
        'failed_post_scripts': 0,
        'regions': set(),
        'hosts': set(),
        'services_by_status': defaultdict(int)
    }

    # Analyze deployment results
    for service_name, regions in deployment_results.items():
        service_success = True
        for region, deployments in regions.items():
            stats['regions'].add(region)
            for deployment in deployments:
                stats['total_deployments'] += 1
                stats['hosts'].add(deployment['host'])

                if deployment['state'] == 'passed':
                    stats['successful_deployments'] += 1
                elif deployment['state'] == 'failed':
                    stats['failed_deployments'] += 1
                    service_success = False

        if service_success:
            stats['services_by_status']['successful'] += 1
        else:
            stats['services_by_status']['failed'] += 1

    # Analyze post-script results
    for service_name, regions in post_script_results.items():
        for region, scripts in regions.items():
            for script in scripts:
                stats['total_post_scripts'] += 1
                if script['state'] == 'passed':
                    stats['successful_post_scripts'] += 1
                elif script['state'] == 'failed':
                    stats['failed_post_scripts'] += 1

    # Convert sets to counts
    stats['total_regions'] = len(stats['regions'])
    stats['total_hosts'] = len(stats['hosts'])

    return stats


def generate_summary_markdown(deployment_results, post_script_results, stats, metadata):
    """
    Generate a comprehensive markdown summary of the deployment.
    This is the main "dashboard" that gets displayed as a Buildkite annotation.
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")

    # Calculate success rate
    if stats['total_deployments'] > 0:
        success_rate = (stats['successful_deployments'] / stats['total_deployments']) * 100
    else:
        success_rate = 0

    # Header with overall status
    if success_rate >= 95:
        status_emoji = "🎉"
        status_text = "EXCELLENT"
    elif success_rate >= 80:
        status_emoji = "✅"
        status_text = "GOOD"
    elif success_rate >= 60:
        status_emoji = "⚠️"
        status_text = "PARTIAL"
    else:
        status_emoji = "❌"
        status_text = "CRITICAL"

    markdown = f"""
# {status_emoji} Deployment Summary - {status_text}

**Generated:** {timestamp}
**Overall Success Rate:** {success_rate:.1f}% ({stats['successful_deployments']}/{stats['total_deployments']})

---

## 📊 Quick Stats

| Metric | Count |
|--------|--------|
| Services Deployed | {stats['total_services']} |
| Total Deployments | {stats['total_deployments']} |
| Regions | {stats['total_regions']} |
| Hosts | {stats['total_hosts']} |
| Post-Scripts | {stats['total_post_scripts']} |

---

## 🚀 Service Deployment Status
"""

    # Service-by-service breakdown
    for service_name, regions in sorted(deployment_results.items()):
        service_total = 0
        service_success = 0

        # Count totals for this service
        for region, deployments in regions.items():
            for deployment in deployments:
                service_total += 1
                if deployment['state'] == 'passed':
                    service_success += 1

        service_rate = (service_success / service_total * 100) if service_total > 0 else 0
        service_emoji = "✅" if service_rate == 100 else "⚠️" if service_rate > 0 else "❌"

        markdown += f"\n### {service_emoji} {service_name}\n"
        markdown += f"**Success Rate:** {service_rate:.0f}% ({service_success}/{service_total})\n\n"

        # Region breakdown for this service
        for region, deployments in sorted(regions.items()):
            if deployments:
                version = deployments[0]['version']  # All deployments should be same version
                markdown += f"**{region.upper()}** (v{version}): "

                # Group by status for cleaner display
                status_groups = defaultdict(list)
                for deployment in deployments:
                    status_groups[deployment['state']].append(deployment['host'])

                status_parts = []
                for state, hosts in status_groups.items():
                    emoji = '✅' if state == 'passed' else '❌' if state == 'failed' else '🏃' if state == 'running' else '❓'
                    status_parts.append(f"{emoji} {', '.join(hosts)}")

                markdown += " | ".join(status_parts) + "\n\n"

    # Failures section (if any)
    failures = []
    for service_name, regions in deployment_results.items():
        for region, deployments in regions.items():
            for deployment in deployments:
                if deployment['state'] == 'failed':
                    failures.append({
                        'service': service_name,
                        'region': region,
                        'host': deployment['host'],
                        'version': deployment['version'],
                        'exit_status': deployment.get('exit_status', 'unknown')
                    })

    if failures:
        markdown += "\n## ❌ Failed Deployments\n\n"
        markdown += "| Service | Region | Host | Version | Exit Code |\n"
        markdown += "|---------|--------|------|---------|----------|\n"

        for failure in failures:
            markdown += f"| {failure['service']} | {failure['region']} | {failure['host']} | {failure['version']} | {failure['exit_status']} |\n"

    # Post-script summary (if any)
    if post_script_results and stats['total_post_scripts'] > 0:
        markdown += f"\n## 🔧 Post-Deployment Scripts\n\n"
        script_success_rate = (stats['successful_post_scripts'] / stats['total_post_scripts'] * 100) if stats['total_post_scripts'] > 0 else 0
        markdown += f"**Success Rate:** {script_success_rate:.1f}% ({stats['successful_post_scripts']}/{stats['total_post_scripts']})\n\n"

        for service_name, regions in sorted(post_script_results.items()):
            for region, scripts in regions.items():
                for script in scripts:
                    status = "✅" if script['state'] == 'passed' else "❌" if script['state'] == 'failed' else "🏃"
                    markdown += f"- {status} **{script['script']}** on {script['host']} ({service_name})\n"

    # Metadata section (if available)
    if metadata:
        generation_time = metadata.get('generation-timestamp', 'unknown')
        markdown += f"\n---\n\n*Pipeline generated at: {generation_time}*\n"

    return markdown


def create_buildkite_annotation(markdown_content):
    """
    Create a Buildkite annotation with the deployment summary.
    Uses the buildkite-agent annotate command.
    """
    annotation_style = "info"  # Can be: success, info, warning, error

    if getenv("BUILDKITE_COMPUTE_TYPE") is not None:
        print("Creating Buildkite annotation...")

        # Write markdown to temporary file
        temp_file = "deployment_summary.md"
        with open(temp_file, 'w') as f:
            f.write(markdown_content)

        # Create annotation
        annotate_cmd = f'buildkite-agent annotate --style {annotation_style} --context deployment-summary < {temp_file}'
        result = system(annotate_cmd)

        if result == 0:
            print("✅ Deployment summary annotation created successfully!")
        else:
            print(f"❌ Failed to create annotation (exit code: {result})")
    else:
        print("Running locally - would create annotation with content:")
        print("=" * 50)
        print(markdown_content)
        print("=" * 50)


def main():
    """
    Main function that orchestrates the deployment summary generation.
    Think of this as your deployment "after-action report" generator.
    """
    print("=== Generating Deployment Summary ===")

    # Get build data from API
    build_data = get_current_build_data()
    if not build_data:
        print("ERROR: Cannot fetch build data - summary generation failed")
        return

    print(f"Analyzing build #{build_data.get('number', 'unknown')} with {len(build_data.get('jobs', []))} jobs")

    # Parse deployment results
    deployment_results, post_script_results = parse_deployment_jobs(build_data)

    if not deployment_results:
        print("WARNING: No deployment jobs found in build data")
        # Still create a summary showing this
        markdown = f"""
# ⚠️ Deployment Summary - No Deployments Found

**Generated:** {datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")}

No deployment jobs were detected in this build. This could mean:
- The deployment pipeline hasn't started yet
- Job naming doesn't match expected patterns
- This summary ran too early in the pipeline

Check the build logs and pipeline configuration.
"""
        create_buildkite_annotation(markdown)
        return

    # Calculate statistics
    stats = calculate_deployment_statistics(deployment_results, post_script_results)

    # Load metadata for additional context
    metadata = get_metadata_artifact()

    # Generate the comprehensive summary
    print(f"Generating summary for {stats['total_services']} services across {stats['total_regions']} regions...")
    markdown_summary = generate_summary_markdown(deployment_results, post_script_results, stats, metadata)

    # Create the Buildkite annotation
    create_buildkite_annotation(markdown_summary)

    print("=== Summary Generation Complete ===")
    print(f"📊 Processed {stats['total_deployments']} deployments")
    print(f"✅ Success rate: {(stats['successful_deployments']/stats['total_deployments']*100):.1f}%" if stats['total_deployments'] > 0 else "No deployments to analyze")


if __name__ == "__main__":
    main()
