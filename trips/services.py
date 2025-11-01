import requests

def get_route(current_location, pickup_location, dropoff_location, api_key):
    base_url = "https://api.openrouteservice.org/v2/directions/driving-car"
    headers = {"Authorization": api_key, "Content-Type": "application/json"}

    # You could improve this by converting addresses to coordinates (geocoding)
    # For now, we’ll expect coordinates: [longitude, latitude]
    body = {
        "coordinates": [current_location, pickup_location, dropoff_location]
    }

    response = requests.post(base_url, json=body, headers=headers)
    data = response.json()
    return data
