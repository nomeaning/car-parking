import os
from dotenv import load_dotenv
from supabase import Client, create_client

load_dotenv()

url: str = os.getenv("SUPABASE_URL")
key: str = os.getenv("SUPABASE_KEY")

supabase: Client = create_client(url, key)


def check_connection():
    # Executes a test ping/query against your database
    response = (
        supabase.table("parking_spots").select("*").limit(1).execute()
    )
    print("Connected successfully! Response:", response.data)


if __name__ == "__main__":
    check_connection()