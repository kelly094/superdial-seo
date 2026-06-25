from google.ads.googleads.client import GoogleAdsClient

client = GoogleAdsClient.load_from_storage("google-ads.yaml")
customer_service = client.get_service("CustomerService")
accessible_customers = customer_service.list_accessible_customers()

print("Connected! Accessible accounts:")
for resource_name in accessible_customers.resource_names:
    print(f"  {resource_name}")
