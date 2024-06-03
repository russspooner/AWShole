import boto3
from collections import defaultdict
import argparse
import os

def get_vpcs(ec2):
    response = ec2.describe_vpcs()
    return response['Vpcs']

def get_s3_buckets(s3):
    response = s3.list_buckets()
    return response['Buckets']

def get_lambda_functions(lambda_client):
    response = lambda_client.list_functions()
    return response['Functions']

def get_app_gateways(client):
    response = client.describe_load_balancers()
    return response['LoadBalancers']

def get_ec2_instances(ec2):
    response = ec2.describe_instances()
    instances = []
    for reservation in response['Reservations']:
        for instance in reservation['Instances']:
            instances.append(instance)
    return instances

def get_tags(client, resource_id, resource_type):
    if resource_type == 'ec2':
        response = client.describe_tags(Filters=[{'Name': 'resource-id', 'Values': [resource_id]}])
        tags = {tag['Key']: tag['Value'] for tag in response['Tags']}
    elif resource_type == 'elbv2':
        response = client.describe_tags(ResourceArns=[resource_id])
        tags = {tag['Key']: tag['Value'] for tag in response['TagDescriptions'][0]['Tags']}
    elif resource_type == 'vpc':
        response = client.describe_tags(Filters=[{'Name': 'resource-id', 'Values': [resource_id]}])
        tags = {tag['Key']: tag['Value'] for tag in response['Tags']}
    else:
        tags = {}
    return tags

def generate_html_tree(tree):
    html = "<!DOCTYPE html><html><head><title>AWS Resources</title>"
    html += "<style>.tree {list-style-type: none;}"
    html += ".tree li {margin: 0; padding: 10px 5px 0 5px; position: relative;}"
    html += ".tree li::before {content: ''; left: -20px; position: absolute; top: 20px; width: 1px; height: calc(100% - 20px); background: #ccc;}"
    html += ".tree li::after {content: ''; position: absolute; top: 20px; left: -20px; width: 20px; height: 1px; background: #ccc;}"
    html += ".tree li:last-child::before {height: calc(100% - 20px);}"
    html += ".tree li:last-child::after {display: none;}"
    html += ".tree li .parent {cursor: pointer;}"
    html += ".tree li .parent::before {content: '+'; color: #aaa; display: inline-block; margin-right: 5px;}"
    html += ".tree li.open .parent::before {content: '-';}"
    html += ".tree li .children {display: none;}"
    html += ".tree li.open .children {display: block;}"
    html += "</style></head><body><ul class='tree'>"
    for key, value in tree.items():
        html += "<li><span class='parent'>" + key + "</span>"
        html += "<ul class='children'>"
        if isinstance(value, dict):
            for sub_key, sub_value in value.items():
                if isinstance(sub_value, list):
                    for item in sub_value:
                        if isinstance(item, dict):
                            for resource_id, tags in item.items():
                                tag_str = " [{}]".format(", ".join(f"{k}: {v}" for k, v in tags.items()))
                                html += "<li>" + resource_id + tag_str + "</li>"
                        else:
                            html += "<li>" + str(item) + "</li>"
                else:
                    html += "<li>" + sub_key + "</li>"
        html += "</ul></li>"
    html += "</ul><script>"
    html += "var toggler = document.getElementsByClassName('parent');"
    html += "var i;"
    html += "for (i = 0; i < toggler.length; i++) {"
    html += "toggler[i].addEventListener('click', function() {"
    html += "this.parentElement.querySelector('.children').classList.toggle('open');"
    html += "});"
    html += "}"
    html += "</script></body></html>"
    return html

def generate_ascii_tree(tree):
    ascii_tree = ""

    def traverse(node, level=0):
        nonlocal ascii_tree
        for key, value in node.items():
            ascii_tree += "|  " * level + "+--" + key + "\n"
            if isinstance(value, dict):
                traverse(value, level + 1)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        for resource_id, tags in item.items():
                            tag_str = " [{}]".format(", ".join(f"{k}: {v}" for k, v in tags.items()))
                            ascii_tree += "|  " * (level + 1) + "+--" + resource_id + tag_str + "\n"
                    else:
                        ascii_tree += "|  " * (level + 1) + "+--" + str(item) + "\n"

    traverse(tree)
    return ascii_tree

def main():
    parser = argparse.ArgumentParser(description="Query AWS resources and display them in an HTML or ASCII tree diagram.")
    parser.add_argument("--profile", help="AWS profile name to use for authentication")
    parser.add_argument("--region", help="AWS region to query resources from")
    parser.add_argument("--config", help="Path to AWS config file")
    parser.add_argument("--format", choices=['html', 'ascii'], default='html', help="Output format (default: html)")
    parser.add_argument("--output", help="Output file name")
    args = parser.parse_args()

    session_kwargs = {}
    if args.profile:
        session_kwargs['profile_name'] = args.profile
    if args.region:
        session_kwargs['region_name'] = args.region
    if args.config:
        session_kwargs['config'] = args.config

    session = boto3.Session(**session_kwargs)

    ec2 = session.client('ec2')
    s3 = session.client('s3')
    lambda_client = session.client('lambda')
    client = session.client('elbv2')

    vpcs = get_vpcs(ec2)
    s3_buckets = get_s3_buckets(s3)
    lambda_functions = get_lambda_functions(lambda_client)
    app_gateways = get_app_gateways(client)
    ec2_instances = get_ec2_instances(ec2)

    tree = defaultdict(lambda: defaultdict(list))

    for vpc in vpcs:
        vpc_id = vpc['VpcId']
        tags = get_tags(ec2, vpc_id, 'vpc')
        tree['VPCs'][vpc_id].append({'Tags': tags})

        for bucket in s3_buckets:
            bucket_name = bucket['Name']
            tags = get_tags(s3, bucket_name, 's3')
            tree['VPCs'][vpc_id].append({'S3 Buckets': [{bucket_name: tags}]})

        for function in lambda_functions:
            function_name = function['FunctionName']
            tags = get_tags(lambda_client, function['FunctionArn'], 'lambda')
            tree['VPCs'][vpc_id].append({'Lambda Functions': [{function_name: tags}]})

        for gateway in app_gateways:
            gateway_name = gateway['LoadBalancerName']
            tags = get_tags(client, gateway['LoadBalancerArn'], 'elbv2')
            tree['VPCs'][vpc_id].append({'App Gateways': [{gateway_name: tags}]})

        for instance in ec2_instances:
            if instance.get('VpcId') == vpc_id:
                instance_id = instance['InstanceId']
                tags = get_tags(ec2, instance_id, 'ec2')
                tree['VPCs'][vpc_id].append({'EC2 Instances': [{instance_id: tags}]})

    if args.format == 'html':
        output_content = generate_html_tree(tree)
        file_extension = 'html'
    else:
        output_content = generate_ascii_tree(tree)
        file_extension = 'txt'

    # Use AWS profile name for output filename if not provided
    if args.output:
        output_filename = args.output
    elif args.profile:
        output_filename = args.profile + '.' + file_extension
    else:
        output_filename = 'output.' + file_extension

    with open(output_filename, 'w') as output_file:
        output_file.write(output_content)

if __name__ == "__main__":
    main()

