from openai import OpenAI

client = OpenAI(api_key="sk-proj-MVjDtCurQcmIVv3X90ypT3BlbkFJrPVDMqcJWDype88CWATS")

try:
    models = client.models.list()
    print("Key is valid! You have access to models.")
    print(f"First few models: {models.data[:3]}")
except Exception as e:
    print(f"Key is NOT working: {e}")