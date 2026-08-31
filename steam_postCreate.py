import json
import os

def postItemCreated(folderPath, published_id):

    json_file_path = os.path.join(folderPath, "modinfo.json")
    
    with open(json_file_path, 'r') as file:
        data = json.load(file)

    data['uRL'] = "https://steamcommunity.com/sharedfiles/filedetails/?id=%d" % published_id

    with open(json_file_path, 'w') as file:
        json.dump(data, file, indent=4)