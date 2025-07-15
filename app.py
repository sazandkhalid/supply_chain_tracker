import streamlit as st
import boto3
import pandas as pd

st.title("Supply Chain Visibility Dashboard")

dynamodb = boto3.resource('dynamodb', region_name='eu-north-1')
table = dynamodb.Table('Shipments')

def fetch_all_shipments():
    response = table.scan()
    items = response['Items']
    return pd.DataFrame(items)

df = fetch_all_shipments()

if df.empty:
    st.warning("No shipment data found.")
else:
    st.subheader("All Shipments")
    st.dataframe(df)

    # Active Shipments
    active_df = df[df['status'] == 'IN_TRANSIT']
    st.subheader("Active Shipments")
    st.dataframe(active_df)

    # Map
    if 'lat' in df.columns and 'lon' in df.columns:
        map_df = df[['lat', 'lon']].dropna().astype(float)
        st.subheader("Shipment Locations Map")
        st.map(map_df)

    # Status Bar Chart
    st.subheader("Delivery Status Breakdown")
    status_counts = df['status'].value_counts()
    st.bar_chart(status_counts)

