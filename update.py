# updating status 
import boto3
import random

dynamodb = boto3.resource('dynamodb', region_name='eu-north-1')
table = dynamodb.Table('Shipments')

def update_random_items(n=20):
    scan = table.scan()
    items = scan.get("Items", [])
    sample = random.sample(items, n)

    for item in sample:
        new_status = random.choice(["DELIVERED", "LATE"])
        table.update_item(
            Key={"shipmentId": item["shipmentId"], "timestamp": item["timestamp"]},
            UpdateExpression="SET #s = :val",
            ExpressionAttributeValues={":val": new_status},
            ExpressionAttributeNames={"#s": "status"}
        )

update_random_items()