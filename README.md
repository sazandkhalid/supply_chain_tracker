# Supply Chain Visibility Platform

AWS-powered real-time shipment tracking and analytics dashboard.

---

## Overview

This project is a full-stack supply chain visibility solution built on AWS. It simulates real-time shipment events, ingests them via API Gateway and Lambda, stores them in DynamoDB and S3, and provides an interactive analytics dashboard built with Streamlit.

---

## Features

- Event simulation for shipments (location, status, timestamp)
- API Gateway endpoint to receive shipment batches
- AWS Lambda function to validate, store in DynamoDB, archive in S3
- DynamoDB table for querying active and historical shipments
- S3 archive of batch JSON files for auditing
- Streamlit dashboard for analytics:
  - Map of shipment locations
  - Delivery status breakdown
  - Active shipments table

---
## Architecture Diagram 
               +--------------------------------------+
               |           Event Simulator            |
               |       (Python CLI Script)            |
               +-----------------+--------------------+
                                 |
                                 v
               +--------------------------------------+
               |            API Gateway               |
               |      (HTTP POST /event)              |
               +-----------------+--------------------+
                                 |
                                 v
               +--------------------------------------+
               |            AWS Lambda                |
               |   - Parse & Validate Batch           |
               |   - Write to DynamoDB                |
               |   - Archive Batch to S3              |
               +--------+----------------+------------+
                        |                |
               +--------v-----+    +-----v----------+
               |   DynamoDB    |    |      S3       |
               | Shipments Table|   | Batch Archives|
               +--------+------+    +---------------+
                        |
                        v
               +--------------------------------------+
               |       Streamlit Dashboard            |
               | - Query DynamoDB                     |
               | - Display Maps, Charts, Tables       |
               +--------------------------------------+

## AWS Services Used

- **API Gateway**: Receives HTTP POST requests with event batches.
- **AWS Lambda**: Stateless event processor.
- **DynamoDB**: NoSQL database for real-time shipment status.
- **S3**: Stores batch JSON archives.
- **IAM**: Manages permissions for Lambda roles.
- **CloudWatch**: Logs Lambda execution and errors.

##How It Works

1️⃣ **Simulation**:  
The `event_simulator.py` script generates batches of random shipment events and POSTs them to the API Gateway endpoint.

2️⃣ **Ingestion**:  
API Gateway forwards events to a Lambda function.

3️⃣ **Processing**:  
Lambda validates and parses the batch.
- Stores individual items in DynamoDB.
- Archives the entire batch as a JSON file in S3.

4️⃣ **Analytics**:  
Streamlit dashboard connects to DynamoDB to visualize:
- Active shipments on a map.
- Delivery status breakdown.
- Tables of shipment records.

