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

def display_tree(tree, level=0):
    for key, value in tree.items():
        print("|  " * level + "+--" + key)
        if isinstance(value, dict):
            display_tree(value, level + 1)
        elif isinstance(value, list):
            for item in value:
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
            tree['VPCs'][vpc_id]['S3 Buckets'].append(bucket['Name'])

        for function in lambda_functions:
            tree['VPCs'][vpc_id]['Lambda Functions'].append(function['FunctionName'])

        for gateway in app_gateways:
            tree['VPCs'][vpc_id]['App Gateways'].append(gateway['LoadBalancerName'])

        for instance in ec2_instances:
            if instance.get('VpcId') == vpc_id:
                tree['VPCs'][vpc_id]['EC2 Instances'].append(instance['InstanceId'])

    display_tree(tree)

if __name__ == "__main__":
    main()
