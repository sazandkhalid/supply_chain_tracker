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


