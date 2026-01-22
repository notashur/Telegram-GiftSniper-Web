
from gifts import GIFT_MAPPINGS
import requests
from PIL import Image
from io import BytesIO
import os

# Base URL for gift images
fetch_image_by_id = "https://cdn.changes.tg/gifts/originals/{id}/Original.png"

def fetch_and_resize_gift_image(gift_id, size=(50, 50)):
    """
    Fetch and resize the gift image to specified dimensions.
    
    :param gift_id: The ID of the gift
    :param size: Tuple of (width, height) for output image
    :return: Resized image bytes or None if failed
    """
    try:
        response = requests.get(fetch_image_by_id.format(id=gift_id))
        if response.status_code == 200:
            # Open image and resize
            img = Image.open(BytesIO(response.content))
            img = img.resize(size, Image.LANCZOS)
            
            # Convert back to bytes
            img_byte_arr = BytesIO()
            img.save(img_byte_arr, format='PNG', optimize=True)

            return img_byte_arr.getvalue()
    except Exception as e:
        print(f"Error processing image for {gift_id}: {str(e)}")
    return None

def save_resized_gift_image(gift_id, folder_path):
    """
    Save resized gift image to specified folder
    
    :param gift_id: The ID of the gift
    :param folder_path: Path to save folder
    :return: Path to saved image or None
    """
    # Create folder if it doesn't exist
    os.makedirs(folder_path, exist_ok=True)
    
    image_bytes = fetch_and_resize_gift_image(gift_id)
    if image_bytes:
        file_path = os.path.join(folder_path, f"{gift_id}.png")
        with open(file_path, 'wb') as f:
            f.write(image_bytes)
        return file_path
    return None

if __name__ == "__main__":
    output_folder = "../static/gifts"  # Changed to match web path
    success_count = 0
    
    for gift_id, gift_name in GIFT_MAPPINGS.items():
        print(f"Processing {gift_name} ({gift_id})...")
        image_path = save_resized_gift_image(gift_id, output_folder)
        if image_path:
            success_count += 1
            print(f"✓ Saved resized image to {image_path}")
        else:
            print(f"✗ Failed to process image")
    
    print(f"\nCompleted! Successfully processed {success_count}/{len(GIFT_MAPPINGS)} gifts")