import boto3
from collections import defaultdict

def get_vpcs():
    ec2 = boto3.client('ec2')
    response = ec2.describe_vpcs()
    return response['Vpcs']

def get_s3_buckets():
    s3 = boto3.client('s3')
    response = s3.list_buckets()
    return response['Buckets']

def get_lambda_functions():
    lambda_client = boto3.client('lambda')
    response = lambda_client.list_functions()
    return response['Functions']

def get_app_gateways():
    client = boto3.client('elbv2')
    response = client.describe_load_balancers()
    return response['LoadBalancers']

def get_ec2_instances():
    ec2 = boto3.client('ec2')
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
    vpcs = get_vpcs()
    s3_buckets = get_s3_buckets()
    lambda_functions = get_lambda_functions()
    app_gateways = get_app_gateways()
    ec2_instances = get_ec2_instances()

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
