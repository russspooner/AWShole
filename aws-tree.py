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
        response = client.describe_tags(Resources=[resource_id])
        tags = {tag['Key']: tag['Value'] for tag in response['Tags']}
    elif resource_type == 'elbv2':
        response = client.describe_tags(ResourceArns=[resource_id])
        tags = {tag['Key']: tag['Value'] for tag in response['TagDescriptions'][0]['Tags']}
    else:
        tags = {}
    return tags

def display_tree(tree, level=0):
    for key, value in tree.items():
        print("|  " * level + "+--" + key)
        if isinstance(value, dict):
            display_tree(value, level + 1)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    for resource_id, tags in item.items():
                        tag_str = " [{}]".format(", ".join(f"{k}: {v}" for k, v in tags.items()))
                        print("|  " * (level + 1) + "+--" + resource_id + tag_str)
                else:
                    print("|  " * (level + 1) + "+--" + str(item))

def main():
    parser = argparse.ArgumentParser(description="Query AWS resources and display them in an ASCII tree diagram.")
    parser.add_argument("--profile", help="AWS profile name to use for authentication")
    parser.add_argument("--region", help="AWS region to query resources from")
    parser.add_argument("--config", help="Path to AWS config file")
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

    tree = defaultdict(dict)

    for vpc in vpcs:
        vpc_id = vpc['VpcId']
        tree['VPCs'][vpc_id] = defaultdict(list)

        for bucket in s3_buckets:
            bucket_name = bucket['Name']
            tags = get_tags(s3, bucket_name, 's3')
            tree['VPCs'][vpc_id]['S3 Buckets'].append({bucket_name: tags})

        for function in lambda_functions:
            function_name = function['FunctionName']
            tags = get_tags(lambda_client, function['FunctionArn'], 'lambda')
            tree['VPCs'][vpc_id]['Lambda Functions'].append({function_name: tags})

        for gateway in app_gateways:
            gateway_name = gateway['LoadBalancerName']
            tags = get_tags(client, gateway['LoadBalancerArn'], 'elbv2')
            tree['VPCs'][vpc_id]['App Gateways'].append({gateway_name: tags})

        for instance in ec2_instances:
            if instance.get('VpcId') == vpc_id:
                instance_id = instance['InstanceId']
                tags = get_tags(ec2, instance_id, 'ec2')
                tree['VPCs'][vpc_id]['EC2 Instances'].append({instance_id: tags})

    display_tree(tree)

if __name__ == "__main__":
    main()
