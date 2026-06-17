"""
AWS CARE Operational Review - Automated Findings Engine
=======================================================
This Lambda function performs an automated operational review across your
AWS environment, checking for End-of-Life (EOL) risks, patching gaps,
and Trusted Advisor findings across all 5 Well-Architected pillars.

Tools Available:
- generate_care_report    : Full CARE review with pillar scores
- check_trusted_advisor   : Trusted Advisor findings across all pillars
- check_eks_versions      : EKS cluster version vs EOL dates
- check_rds_engines       : RDS engine versions and auto-upgrade status
- check_lambda_runtimes   : Lambda functions on deprecated runtimes
- check_elasticache_versions : ElastiCache engine versions
- check_opensearch_versions  : OpenSearch domain versions
- check_emr_versions      : EMR cluster release versions
- check_patch_compliance  : EC2 patch compliance via SSM
- check_health_events     : AWS Health scheduled maintenance & notifications
- get_upgrade_recommendations : Prioritized upgrade action list

Requirements:
- Python 3.12+
- IAM role with ReadOnlyAccess
- Enterprise or Business Support plan (for Trusted Advisor)
"""

import json
import boto3
from datetime import datetime

# EKS End of Life dates - update periodically from:
# https://docs.aws.amazon.com/eks/latest/userguide/kubernetes-versions.html
EKS_EOL = {
    "1.27": "2025-07-24",
    "1.28": "2025-11-26",
    "1.29": "2026-03-23",
    "1.30": "2026-07-23",
    "1.31": "2026-11-23",
    "1.32": "2027-03-23",
    "1.33": "2027-07-23"
}

# Lambda runtimes that are deprecated or approaching EOL
LAMBDA_DEPRECATED = [
    "python3.7", "python3.8",
    "nodejs14.x", "nodejs16.x",
    "dotnet6", "dotnetcore3.1",
    "ruby2.7", "java8", "go1.x"
]


def check_eks_versions(event):
    """Check all EKS clusters for EOL status"""
    eks = boto3.client('eks')
    clusters = eks.list_clusters()['clusters']
    results = []
    for name in clusters:
        info = eks.describe_cluster(name=name)['cluster']
        version = info['version']
        eol = EKS_EOL.get(version, "Unknown")
        days = None
        if eol != "Unknown":
            days = (datetime.strptime(eol, "%Y-%m-%d") - datetime.now()).days
        results.append({
            "cluster": name,
            "version": version,
            "eol_date": eol,
            "days_remaining": days,
            "urgency": "CRITICAL" if days and days < 60
                       else "WARNING" if days and days < 180
                       else "OK"
        })
    return results


def check_rds_engines(event):
    """Check all RDS instances for engine version status"""
    rds = boto3.client('rds')
    instances = rds.describe_db_instances()['DBInstances']
    results = []
    for db in instances:
        results.append({
            "instance": db['DBInstanceIdentifier'],
            "engine": db['Engine'],
            "version": db['EngineVersion'],
            "auto_upgrade": db.get('AutoMinorVersionUpgrade', False),
            "multi_az": db.get('MultiAZ', False)
        })
    return results


def check_lambda_runtimes(event):
    """Check all Lambda functions for deprecated runtimes"""
    lam = boto3.client('lambda')
    functions = lam.list_functions()['Functions']
    results = []
    for fn in functions:
        runtime = fn.get('Runtime', 'N/A')
        results.append({
            "function": fn['FunctionName'],
            "runtime": runtime,
            "deprecated": runtime in LAMBDA_DEPRECATED,
            "last_modified": fn.get('LastModified', '')
        })
    return results


def check_elasticache_versions(event):
    """Check ElastiCache clusters for engine version"""
    ec = boto3.client('elasticache')
    results = []
    try:
        clusters = ec.describe_cache_clusters()['CacheClusters']
        for c in clusters:
            results.append({
                "cluster": c['CacheClusterId'],
                "engine": c['Engine'],
                "version": c['EngineVersion'],
                "auto_upgrade": c.get('AutoMinorVersionUpgrade', False),
                "status": c['CacheClusterStatus']
            })
    except Exception as e:
        results.append({"error": str(e)})
    return results


def check_opensearch_versions(event):
    """Check OpenSearch domains for version currency"""
    os_client = boto3.client('opensearch')
    results = []
    try:
        domains = os_client.list_domain_names()['DomainNames']
        for d in domains:
            info = os_client.describe_domain(DomainName=d['DomainName'])['DomainStatus']
            version = info.get('EngineVersion', 'Unknown')
            results.append({
                "domain": d['DomainName'],
                "version": version,
                "instance_type": info['ClusterConfig']['InstanceType'],
                "instance_count": info['ClusterConfig']['InstanceCount']
            })
    except Exception as e:
        results.append({"error": str(e)})
    return results


def check_emr_versions(event):
    """Check EMR clusters for release version currency"""
    emr = boto3.client('emr')
    results = []
    try:
        clusters = emr.list_clusters(ClusterStates=['RUNNING', 'WAITING'])['Clusters']
        for c in clusters:
            results.append({
                "cluster": c['Name'],
                "id": c['Id'],
                "release": c.get('ReleaseLabel', 'Unknown'),
                "status": c['Status']['State']
            })
    except Exception as e:
        results.append({"error": str(e)})
    return results


def check_patch_compliance(event):
    """Check SSM patch compliance for managed instances"""
    ssm = boto3.client('ssm')
    try:
        states = ssm.describe_instance_patch_states()
        return [{
            "instance": i['InstanceId'],
            "missing_patches": i.get('MissingCount', 0),
            "failed_patches": i.get('FailedCount', 0),
            "installed": i.get('InstalledCount', 0)
        } for i in states.get('InstancePatchStates', [])]
    except Exception as e:
        return [{"message": f"No SSM-managed instances found: {str(e)}"}]


def check_health_events(event):
    """Check AWS Health for upcoming maintenance and EOL notifications"""
    health = boto3.client('health', region_name='us-east-1')
    results = []
    try:
        events = health.describe_events(
            filter={
                'eventTypeCategories': ['scheduledChange', 'accountNotification'],
                'eventStatusCodes': ['open', 'upcoming']
            }
        )['events']
        for e in events:
            results.append({
                "service": e.get('service', 'Unknown'),
                "event_type": e.get('eventTypeCode', ''),
                "category": e.get('eventTypeCategory', ''),
                "status": e.get('statusCode', ''),
                "start_time": str(e.get('startTime', '')),
                "description": e.get('eventTypeCode', '').replace('_', ' ')
            })
    except Exception as ex:
        results.append({"message": f"Health API unavailable: {str(ex)}"})
    return results


def get_upgrade_recommendations(event):
    """Generate prioritized upgrade recommendations"""
    recommendations = []
    for fn in check_lambda_runtimes(event):
        if fn.get('deprecated'):
            recommendations.append({"service": "Lambda", "resource": fn['function'],
                "action": f"Upgrade from {fn['runtime']}", "priority": "HIGH", "type": "EOL"})
    for cluster in check_eks_versions(event):
        if cluster.get('urgency') in ['CRITICAL', 'WARNING']:
            recommendations.append({"service": "EKS", "resource": cluster['cluster'],
                "action": f"Upgrade from {cluster['version']} (EOL {cluster['eol_date']})",
                "priority": cluster['urgency'], "type": "EOL"})
    for db in check_rds_engines(event):
        if not db.get('auto_upgrade'):
            recommendations.append({"service": "RDS", "resource": db['instance'],
                "action": f"Enable auto upgrade for {db['engine']} {db['version']}",
                "priority": "MEDIUM", "type": "PATCHING"})
    for p in check_patch_compliance(event):
        missing = p.get('missing_patches', 0)
        if missing > 0:
            recommendations.append({"service": "EC2", "resource": p.get('instance', ''),
                "action": f"Apply {missing} missing patches",
                "priority": "HIGH" if missing > 5 else "MEDIUM", "type": "PATCHING"})
    return recommendations


def check_trusted_advisor(event):
    """Pull Trusted Advisor findings across all pillars"""
    ta = boto3.client('trustedadvisor', region_name='us-east-1')
    results = {
        "cost_optimization": [], "performance": [], "security": [],
        "fault_tolerance": [], "service_limits": [], "operational_excellence": [],
        "summary": {"total_checks": 0, "action_required": 0, "warning": 0, "ok": 0}
    }
    pillar_map = {
        "cost_optimizing": "cost_optimization", "performance": "performance",
        "security": "security", "fault_tolerance": "fault_tolerance",
        "service_limits": "service_limits", "operational_excellence": "operational_excellence"
    }
    try:
        paginator = ta.get_paginator('list_recommendations')
        for page in paginator.paginate():
            for rec in page.get('recommendationSummaries', []):
                results["summary"]["total_checks"] += 1
                status = rec.get('status', 'ok')
                pillar = rec.get('pillar', 'operational_excellence')
                mapped_pillar = pillar_map.get(pillar, 'operational_excellence')
                finding = {
                    "id": rec.get('id', ''), "name": rec.get('name', ''),
                    "status": status, "pillar": mapped_pillar,
                    "resources_affected": rec.get('resourcesAggregates', {}).get('errorCount', 0)
                                        + rec.get('resourcesAggregates', {}).get('warningCount', 0)
                }
                if status == 'error':
                    results["summary"]["action_required"] += 1
                    results[mapped_pillar].append(finding)
                elif status == 'warning':
                    results["summary"]["warning"] += 1
                    results[mapped_pillar].append(finding)
                else:
                    results["summary"]["ok"] += 1
    except Exception as e:
        results["error"] = f"Trusted Advisor API error: {str(e)}"
    return results


def generate_care_report(event):
    """Generate a full CARE-style operational review report"""
    report = {
        "report_type": "CARE Operational Review",
        "generated_at": datetime.now().isoformat(),
        "pillars": {}
    }

    ta = check_trusted_advisor(event)

    # Security
    security_findings = ta.get("security", [])
    report["pillars"]["security"] = {
        "findings": security_findings,
        "score": "RED" if any(f.get('status') == 'error' for f in security_findings)
                 else "YELLOW" if security_findings else "GREEN"
    }

    # Reliability
    reliability_findings = ta.get("fault_tolerance", [])
    for c in check_eks_versions(event):
        if c.get('urgency') in ['CRITICAL', 'WARNING']:
            reliability_findings.append({"name": f"EKS {c['cluster']} on {c['version']}",
                "status": "error" if c['urgency'] == 'CRITICAL' else "warning",
                "pillar": "fault_tolerance", "resources_affected": 1})
    report["pillars"]["reliability"] = {
        "findings": reliability_findings,
        "score": "RED" if any(f.get('status') == 'error' for f in reliability_findings)
                 else "YELLOW" if reliability_findings else "GREEN"
    }

    # Performance
    perf_findings = ta.get("performance", [])
    report["pillars"]["performance"] = {
        "findings": perf_findings,
        "score": "RED" if any(f.get('status') == 'error' for f in perf_findings)
                 else "YELLOW" if perf_findings else "GREEN"
    }

    # Cost Optimization
    cost_findings = ta.get("cost_optimization", [])
    report["pillars"]["cost_optimization"] = {
        "findings": cost_findings,
        "score": "RED" if any(f.get('status') == 'error' for f in cost_findings)
                 else "YELLOW" if cost_findings else "GREEN"
    }

    # Operational Excellence (EOL + Patching + Service Limits)
    ops_findings = ta.get("operational_excellence", []) + ta.get("service_limits", [])
    for fn in check_lambda_runtimes(event):
        if fn.get('deprecated'):
            ops_findings.append({"name": f"Lambda {fn['function']} - deprecated {fn['runtime']}",
                "status": "error", "pillar": "operational_excellence", "resources_affected": 1})
    for p in check_patch_compliance(event):
        if p.get('missing_patches', 0) > 0:
            ops_findings.append({"name": f"Instance {p['instance']} - {p['missing_patches']} missing patches",
                "status": "warning" if p['missing_patches'] < 5 else "error",
                "pillar": "operational_excellence", "resources_affected": 1})
    report["pillars"]["operational_excellence"] = {
        "findings": ops_findings,
        "score": "RED" if any(f.get('status') == 'error' for f in ops_findings)
                 else "YELLOW" if ops_findings else "GREEN"
    }

    # Summary
    all_findings = []
    for pillar_data in report["pillars"].values():
        all_findings.extend(pillar_data["findings"])
    report["summary"] = {
        "total_findings": len(all_findings),
        "critical": len([f for f in all_findings if f.get('status') == 'error']),
        "warning": len([f for f in all_findings if f.get('status') == 'warning']),
        "pillars_at_risk": [p for p, d in report["pillars"].items() if d["score"] != "GREEN"],
        "ta_summary": ta.get("summary", {})
    }
    return report


def lambda_handler(event, context):
    """Main handler - routes to the appropriate tool"""
    tool = event.get('tool', event.get('name', ''))

    tools = {
        'check_eks_versions': check_eks_versions,
        'check_rds_engines': check_rds_engines,
        'check_lambda_runtimes': check_lambda_runtimes,
        'check_elasticache_versions': check_elasticache_versions,
        'check_opensearch_versions': check_opensearch_versions,
        'check_emr_versions': check_emr_versions,
        'check_patch_compliance': check_patch_compliance,
        'check_health_events': check_health_events,
        'check_trusted_advisor': check_trusted_advisor,
        'get_upgrade_recommendations': get_upgrade_recommendations,
        'generate_care_report': generate_care_report
    }

    if tool in tools:
        result = tools[tool](event)
        return {"statusCode": 200, "body": json.dumps(result, default=str)}

    # No specific tool = return full CARE report
    return {"statusCode": 200, "body": json.dumps(generate_care_report(event), default=str)}
