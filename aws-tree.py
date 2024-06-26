import boto3
from collections import defaultdict
import argparse
from botocore.exceptions import ClientError
import tqdm

def get_vpcs(ec2):
    response = ec2.describe_vpcs()
    return response['Vpcs']

def get_s3_buckets(s3):
    response = s3.list_buckets()
    return response['Buckets']

def get_lambda_functions(lambda_client):
    response = lambda_client.list_functions()
    return response['Functions']

def get_lambda_triggers(lambda_client, function_name):
    response = lambda_client.list_event_source_mappings(FunctionName=function_name)
    triggers = []
    for mapping in response['EventSourceMappings']:
        trigger_info = {'UUID': mapping['UUID'], 'EventSourceArn': mapping['EventSourceArn']}
        # Adding URLs if available
        if 'EventSourceArn' in mapping:
            if mapping['EventSourceArn'].startswith('arn:aws:sqs:'):
                region = mapping['EventSourceArn'].split(':')[3]
                queue_name = mapping['EventSourceArn'].split(':')[-1]
                trigger_info['URL'] = f"https://{region}.console.aws.amazon.com/sqs/v2/home?region={region}#/queues/https%3A%2F%2Fsqs.{region}.amazonaws.com%2F{queue_name}"
            elif mapping['EventSourceArn'].startswith('arn:aws:dynamodb:'):
                region = mapping['EventSourceArn'].split(':')[3]
                table_name = mapping['EventSourceArn'].split(':')[-1]
                trigger_info['URL'] = f"https://{region}.console.aws.amazon.com/dynamodb/home?region={region}#tables:selected={table_name}"
            elif mapping['EventSourceArn'].startswith('arn:aws:kinesis:'):
                region = mapping['EventSourceArn'].split(':')[3]
                stream_name = mapping['EventSourceArn'].split(':')[-1]
                trigger_info['URL'] = f"https://{region}.console.aws.amazon.com/kinesis/home?region={region}#/streams/details/{stream_name}/details"
        triggers.append(trigger_info)
    return triggers if triggers else ["None"]

def get_app_gateways(client):
    response = client.describe_load_balancers()
    return response['LoadBalancers']

def get_api_gateways(api_client):
    response = api_client.get_rest_apis()
    return response['items']

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

def get_sns_encryption(sns, topic_arn):
    try:
        attributes = sns.get_topic_attributes(TopicArn=topic_arn)['Attributes']
        if 'KmsMasterKeyId' in attributes:
            return True
        else:
            return False
    except ClientError as e:
        return False

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

def clean_tree(tree):
    keys_to_delete = []
    for key, value in tree.items():
        if isinstance(value, list) and not value:
            keys_to_delete.append(key)
        elif isinstance(value, dict):
            clean_tree(value)
            if not value:
                keys_to_delete.append(key)
    for key in keys_to_delete:
        del tree[key]

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
    html += ".tree li.open > .parent::before {content: '-';}"
    html += ".tree .children {display: none;}"
    html += ".tree .open > .children {display: block;}"
    html += ".red {color: red;}"
    html += "</style></head><body><ul class='tree'>"

    def generate_html_node(node):
        nonlocal html
        if isinstance(node, dict):
            for key, value in node.items():
                if key == 'URL' and isinstance(value, str):
                    html += f'<li><a href="{value}" target="_blank">{key}</a></li>'
                elif isinstance(value, dict):
                    is_red = value.get('is_red', False)
                    class_name = 'red' if is_red else ''
                    html += f"<li><span class='parent {class_name}' onclick='toggleNode(this)'>" + key + "</span>"
                    html += "<ul class='children'>"
                    generate_html_node(value)
                    html += "</ul></li>"
                elif isinstance(value, list):
                    html += f"<li><span class='parent' onclick='toggleNode(this)'>" + key + "</span>"
                    html += "<ul class='children'>"
                    for item in value:
                        generate_html_node(item)
                    html += "</ul></li>"
                elif key != 'is_red':
                    class_name = 'red' if key == 'is_red' and value else ''
                    html += f"<li class='{class_name}'>" + str(key) + ": " + str(value) + "</li>"
        else:
            html += "<li>" + str(node) + "</li>"

    generate_html_node(tree)

    html += "</ul><script>"
    html += "function toggleNode(element) {"
    html += "var parent = element.parentElement;"
    html += "parent.classList.toggle('open');"
    html += "var children = parent.querySelector('.children');"
    html += "if (children) {"
    html += "children.style.display = children.style.display === 'block' ? 'none' : 'block';"
    html += "}"
    html += "}"
    html += "document.addEventListener('DOMContentLoaded', function() {"
    html += "var parents = document.querySelectorAll('.parent');"
    html += "parents.forEach(function(item) {"
    html += "item.parentElement.classList.add('collapsed');"
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
                color = "\033[91m" if (key == 'is_red' and value) else ""
                reset = "\033[0m" if color else ""
                if key == 'Triggers' and value == ["None"]:
                    ascii_tree += "|  " * level + "+--" + key + "\n"
                elif key == 'URL' and isinstance(value, str):
                    ascii_tree += f"|  " * level + "+--" + color + key + ": " + value + reset + "\n"
                elif isinstance(value, dict):
                    ascii_tree += f"|  " * level + "+--" + color + key + reset + "\n"
                    traverse(value, level + 1)
                elif isinstance(value, list):
                    ascii_tree += f"|  " * level + "+--" + key + "\n"
                    for item in value:
                        traverse(item, level + 1)
                elif key != 'is_red':
                    ascii_tree += f"|  " * level + "+--" + color + str(key) + ": " + str(value) + reset + "\n"
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
    api_client = session.client('apigateway')
    sns_client = session.client('sns')
    sqs_client = session.client('sqs')
    kinesis_client = session.client('kinesis')
    dynamodb_client = session.client('dynamodb')

    region = args.region if args.region else session.region_name

    vpcs = get_vpcs(ec2)
    s3_buckets = get_s3_buckets(s3)
    lambda_functions = get_lambda_functions(lambda_client)
    app_gateways = get_app_gateways(client)
    api_gateways = get_api_gateways(api_client)
    ec2_instances = get_ec2_instances(ec2)

    tree = defaultdict(lambda: {
        'Tags': {},
        'Lambda Functions': [],
        'App Gateways': [],
        'API Gateways': [],
        'EC2 Instances': []
    })

    for vpc in tqdm.tqdm(vpcs, desc="Fetching VPCs"):
        vpc_id = vpc['VpcId']
        tags = get_tags(ec2, vpc_id, 'vpc')
        vpc_url = f"https://console.aws.amazon.com/vpc/home?region={region}#vpcs:VpcId={vpc_id}"
        tree[vpc_id]['Tags'] = tags
        tree[vpc_id]['URL'] = vpc_url

    for function in tqdm.tqdm(lambda_functions, desc="Fetching Lambda Functions"):
        function_name = function['FunctionName']
        function_vpc = function.get('VpcConfig', {}).get('VpcId')
        tags = get_tags(lambda_client, function['FunctionArn'], 'lambda')
        function_url = f"https://console.aws.amazon.com/lambda/home?region={region}#/functions/{function_name}"
        function_info = {
            'Runtime': function['Runtime'],
            'Triggers': get_lambda_triggers(lambda_client, function_name),
            'URL': function_url,
            'is_red': function['Runtime'] != 'nodejs20.x'
        }
        if function_vpc and function_vpc in tree:
            tree[function_vpc]['Lambda Functions'].append({function_name: function_info})

    for gateway in tqdm.tqdm(app_gateways, desc="Fetching App Gateways"):
        gateway_name = gateway['LoadBalancerName']
        gateway_vpc = gateway.get('VpcId')
        tags = get_tags(client, gateway['LoadBalancerArn'], 'elbv2')
        gateway_url = f"https://console.aws.amazon.com/ec2/v2/home?region={region}#LoadBalancers:LoadBalancerName={gateway_name}"
        if gateway_vpc and gateway_vpc in tree:
            tree[gateway_vpc]['App Gateways'].append({gateway_name: tags, 'URL': gateway_url})

    for api_gateway in tqdm.tqdm(api_gateways, desc="Fetching API Gateways"):
        api_gateway_id = api_gateway['id']
        api_gateway_name = api_gateway['name']
        api_gateway_url = f"https://console.aws.amazon.com/apigateway/home?region={region}#/apis/{api_gateway_id}/resources"
        if 'API Gateways' not in tree:
            tree['API Gateways'] = []
        tree['API Gateways'].append({api_gateway_name: {'ID': api_gateway_id, 'URL': api_gateway_url}})

    for instance in tqdm.tqdm(ec2_instances, desc="Fetching EC2 Instances"):
        instance_id = instance['InstanceId']
        instance_vpc = instance['VpcId']
        tags = get_tags(ec2, instance_id, 'ec2')
        instance_url = f"https://console.aws.amazon.com/ec2/v2/home?region={region}#Instances:instanceId={instance_id}"
        if instance_vpc and instance_vpc in tree:
            tree[instance_vpc]['EC2 Instances'].append({instance_id: tags, 'URL': instance_url})

    for bucket in tqdm.tqdm(s3_buckets, desc="Fetching S3 Buckets"):
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
        if not encryption_enabled or http_access:
            bucket_info['is_red'] = True
        if 'S3 Buckets' not in tree:
            tree['S3 Buckets'] = []
        tree['S3 Buckets'].append({bucket_name: bucket_info})

    sns_topics = sns_client.list_topics()['Topics']
    tree['SNS'] = []
    for topic in tqdm.tqdm(sns_topics, desc="Fetching SNS Topics"):
        topic_arn = topic['TopicArn']
        topic_url = f"https://{region}.console.aws.amazon.com/sns/v3/home?region={region}#/topic/{topic_arn}"
        encryption_enabled = get_sns_encryption(sns_client, topic_arn)
        topic_info = {
            'URL': topic_url,
            'Encryption Enabled': encryption_enabled
        }
        if not encryption_enabled:
            topic_info['is_red'] = True
        tree['SNS'].append({topic_arn: topic_info})

    sqs_queues = sqs_client.list_queues().get('QueueUrls', [])
    tree['SQS'] = []
    for queue_url in tqdm.tqdm(sqs_queues, desc="Fetching SQS Queues"):
        tree['SQS'].append({queue_url: {'URL': queue_url}})

    kinesis_streams = kinesis_client.list_streams()['StreamNames']
    tree['Kinesis'] = []
    for stream in tqdm.tqdm(kinesis_streams, desc="Fetching Kinesis Streams"):
        stream_url = f"https://{region}.console.aws.amazon.com/kinesis/home?region={region}#/streams/details/{stream}/details"
        tree['Kinesis'].append({stream: {'URL': stream_url}})

    dynamodb_tables = dynamodb_client.list_tables()['TableNames']
    tree['DynamoDB'] = []
    for table in tqdm.tqdm(dynamodb_tables, desc="Fetching DynamoDB Tables"):
        table_url = f"https://{region}.console.aws.amazon.com/dynamodb/home?region={region}#tables:selected={table}"
        tree['DynamoDB'].append({table: {'URL': table_url}})

    clean_tree(tree)

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
