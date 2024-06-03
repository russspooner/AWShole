import boto3
from collections import defaultdict
import argparse
from botocore.exceptions import ClientError

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

def get_s3_bucket_info(s3, bucket_name):
    # Get number of objects
    objects = s3.list_objects_v2(Bucket=bucket_name)
    object_count = objects['KeyCount']

    # Check public access
    bucket_acl = s3.get_bucket_acl(Bucket=bucket_name)
    public_access = any(grant['Grantee'].get('URI') == 'http://acs.amazonaws.com/groups/global/AllUsers' for grant in bucket_acl['Grants'])

    # Check HTTP accessibility
    try:
        bucket_policy = s3.get_bucket_policy(Bucket=bucket_name)
        http_access = 'http' in bucket_policy['Policy']
    except ClientError as e:
        if e.response['Error']['Code'] == 'NoSuchBucketPolicy':
            http_access = False
        else:
            raise

    # Check encryption
    try:
        encryption = s3.get_bucket_encryption(Bucket=bucket_name)
        encryption_enabled = True
    except ClientError as e:
        if e.response['Error']['Code'] == 'ServerSideEncryptionConfigurationNotFoundError':
            encryption_enabled = False
        else:
            raise

    return object_count, public_access, http_access, encryption_enabled

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

def generate_html_tree(tree, region):
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
    html += ".tree li.open > .children {display: block;}"
    html += "</style></head><body><ul class='tree'>"

    def generate_html_node(node):
        nonlocal html
        if isinstance(node, dict):
            for key, value in node.items():
                if key == 'URL' and isinstance(value, str):
                    html += f'<li><a href="{value}" target="_blank">{key}</a></li>'
                elif isinstance(value, dict):
                    html += "<li><span class='parent'>" + key + "</span>"
                    html += "<ul class='children'>"
                    generate_html_node(value)
                    html += "</ul></li>"
                elif isinstance(value, list):
                    html += "<li><span class='parent'>" + key + "</span>"
                    html += "<ul class='children'>"
                    for item in value:
                        generate_html_node(item)
                    html += "</ul></li>"
                else:
                    html += "<li>" + str(key) + ": " + str(value) + "</li>"
        else:
            html += "<li>" + str(node) + "</li>"

    generate_html_node(tree)

    html += "</ul><script>"
    html += "document.addEventListener('DOMContentLoaded', function() {"
    html += "var toggler = document.querySelectorAll('.parent');"
    html += "toggler.forEach(function(item) {"
    html += "item.addEventListener('click', function() {"
    html += "var parent = this.parentElement;"
    html += "parent.classList.toggle('open');"
    html += "});"
    html += "});"
    html += "});"
    html += "</script></body></html>"
    return html

def generate_ascii_tree(tree):
    ascii_tree = ""

    def traverse(node, level=0):
        nonlocal ascii_tree
        if isinstance(node, dict):
            for key, value in node.items():
                ascii_tree += "|  " * level + "+--" + key + "\n"
                traverse(value, level + 1)
        elif isinstance(node, list):
            for item in node:
                traverse(item, level + 1)
        else:
            ascii_tree += "|  " * level + "+--" + str(node) + "\n"

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

    region = args.region if args.region else session.region_name

    vpcs = get_vpcs(ec2)
    s3_buckets = get_s3_buckets(s3)
    lambda_functions = get_lambda_functions(lambda_client)
    app_gateways = get_app_gateways(client)
    ec2_instances = get_ec2_instances(ec2)

    tree = defaultdict(lambda: {
        'Tags': {},
        'Lambda Functions': [],
        'App Gateways': [],
        'EC2 Instances': []
    })

    for vpc in vpcs:
        vpc_id = vpc['VpcId']
        tags = get_tags(ec2, vpc_id, 'vpc')
        vpc_url = f"https://console.aws.amazon.com/vpc/home?region={region}#vpcs:VpcId={vpc_id}"
        tree[vpc_id]['Tags'] = tags
        tree[vpc_id]['URL'] = vpc_url

    tree['S3 Buckets'] = []

    for bucket in s3_buckets:
        bucket_name = bucket['Name']
        tags = get_tags(s3, bucket_name, 's3')
        bucket_url = f"https://s3.console.aws.amazon.com/s3/buckets/{bucket_name}"
        object_count, public_access, http_access, encryption_enabled = get_s3_bucket_info(s3, bucket_name)
        bucket_info = {
            'URL': bucket_url,
            'Object Count': object_count,
            'Public Access': public_access,
            'HTTP Access': http_access,
            'Encryption Enabled': encryption_enabled
        }
        tree['S3 Buckets'].append({bucket_name: bucket_info})

    for function in lambda_functions:
        function_name = function['FunctionName']
        function_vpc = function.get('VpcConfig', {}).get('VpcId')
        tags = get_tags(lambda_client, function['FunctionArn'], 'lambda')
        function_url = f"https://console.aws.amazon.com/lambda/home?region={region}#/functions/{function_name}"
        function_info = {
            'Runtime': function['Runtime'],
            'Version': function['Version'],
            'URL': function_url
        }
        if function_vpc and function_vpc in tree:
            tree[function_vpc]['Lambda Functions'].append({function_name: function_info})

    for gateway in app_gateways:
        gateway_name = gateway['LoadBalancerName']
        gateway_vpc = gateway.get('VpcId')
        tags = get_tags(client, gateway['LoadBalancerArn'], 'elbv2')
        gateway_url = f"https://console.aws.amazon.com/ec2/v2/home?region={region}#LoadBalancers:LoadBalancerName={gateway_name}"
        if gateway_vpc and gateway_vpc in tree:
            tree[gateway_vpc]['App Gateways'].append({gateway_name: tags, 'URL': gateway_url})

    for instance in ec2_instances:
        instance_id = instance['InstanceId']
        instance_vpc = instance['VpcId']
        tags = get_tags(ec2, instance_id, 'ec2')
        instance_url = f"https://console.aws.amazon.com/ec2/v2/home?region={region}#Instances:instanceId={instance_id}"
        if instance_vpc and instance_vpc in tree:
            tree[instance_vpc]['EC2 Instances'].append({instance_id: tags, 'URL': instance_url})

    if args.format == 'html':
        output_content = generate_html_tree(tree, region)
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
