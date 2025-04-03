import os
import hashlib
import json
from dotenv import load_dotenv
from PIL import Image
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from flask import Flask
from threading import Thread

# Load environment variables
load_dotenv()
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

# Database directory and files
DATA_DIR = "data"
USER_DB_FILE = os.path.join(DATA_DIR, "user_database.json")
OLD_USER_DB_FILE = "user_data/users.json"  # For backward compatibility

# Ensure data directory exists
os.makedirs(DATA_DIR, exist_ok=True)

# Load or initialize user database
def load_user_db():
    # Check for existing database in new location
    if os.path.exists(USER_DB_FILE):
        with open(USER_DB_FILE, "r") as f:
            return json.load(f)
    
    # Check for old database location (backward compatibility)
    if os.path.exists(OLD_USER_DB_FILE):
        with open(OLD_USER_DB_FILE, "r") as f:
            db = json.load(f)
        save_user_db(db)  # Migrate to new location
        os.remove(OLD_USER_DB_FILE)
        return db
    
    # Create new database if none exists
    return {
        "users": {}, 
        "count": 0,
        "total_conversions": 0,
        "total_images": 0
    }

def save_user_db(db):
    with open(USER_DB_FILE, "w") as f:
        json.dump(db, f, indent=2)

def track_user(user_id):
    db = load_user_db()
    user_id_str = str(user_id)
    
    # Convert old list format to new dict format if needed
    if isinstance(db["users"], list):
        db["users"] = {str(u): {"conversions": 0, "images": 0} for u in db["users"]}
    
    if user_id_str not in db["users"]:
        db["users"][user_id_str] = {"conversions": 0, "images": 0}
        db["count"] = len(db["users"])
        save_user_db(db)

# Dictionary to store user data
user_data = {}

# Function to create a unique hash for a user
def create_user_hash(user_id):
    return hashlib.md5(str(user_id).encode()).hexdigest()

# Function to get the user's directory
def get_user_directory(user_id):
    user_hash = create_user_hash(user_id)
    return os.path.join("user_data", user_hash)

# Ensure the user_data directory exists
os.makedirs("user_data", exist_ok=True)

# Initialize the Pyrogram Client
app = Client(
    "image_to_pdf_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
)

# Flask app for keep-alive
flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return "Bot is alive!"

def run_flask():
    flask_app.run(host='0.0.0.0', port=8080)

@app.on_message(filters.command("start"))
async def start(client: Client, message: Message):
    user_id = message.from_user.id
    track_user(user_id)
    await message.reply_text(
        "Welcome! Send me images, and I'll store them in a file directory and convert them into a PDF.\n\n"
        "Available commands:\n"
        "/convert - Create PDF from your images\n"
        "/clear - Reset your images\n"
        "/usage - View your usage statistics\n\n"
        "Just send me images to get started!"
    )

@app.on_message(filters.command("stats") & filters.user(ADMIN_ID))
async def show_stats(client: Client, message: Message):
    try:
        db = load_user_db()
        stats_text = f"""📊 Bot Statistics:
        
Total Users: {db['count']}
Total PDFs Generated: {db['total_conversions']}
Total Images Processed: {db['total_images']}

Top Users:
"""
        # Get top 5 users by conversions
        top_users = sorted(
            [(uid, data) for uid, data in db["users"].items()],
            key=lambda x: x[1]["conversions"],
            reverse=True
        )[:5]
        
        for i, (user_id, data) in enumerate(top_users, 1):
            stats_text += f"{i}. User {user_id}: {data['conversions']} PDFs, {data['images']} images\n"
            
        await message.reply_text(stats_text)
    except Exception as e:
        await message.reply_text(f"Error getting stats: {str(e)}")

@app.on_message(filters.photo)
async def handle_image(client: Client, message: Message):
    user_id = message.from_user.id
    user_dir = get_user_directory(user_id)

    # Create the user's directory if it doesn't exist
    os.makedirs(user_dir, exist_ok=True)

    # Download the image
    image_path = await message.download(file_name=os.path.join(user_dir, f"image_{len(os.listdir(user_dir)) + 1}.jpg"))

    # Store the image path in the user's data
    if user_id not in user_data:
        user_data[user_id] = {"images": []}
    user_data[user_id]["images"].append(image_path)

    await message.reply_text(f"Image received! You have {len(user_data[user_id]['images'])} images. Send more or use /convert to create a PDF.")

@app.on_message(filters.command("convert"))
async def convert_to_pdf(client: Client, message: Message):
    user_id = message.from_user.id
    user_dir = get_user_directory(user_id)

    if user_id not in user_data or not user_data[user_id]["images"]:
        await message.reply_text("No images received yet. Please send some images first.")
        return

    images = user_data[user_id]["images"]

    if len(images) > 1:
        # Ask the user if they want to convert a specific image or all images
        inline_keyboard = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("Convert Specific Image", callback_data="specific_image")],
                [InlineKeyboardButton("Convert All Images to One PDF", callback_data="all_images")],
                [InlineKeyboardButton("Clear All Images", callback_data="clear")],
            ]
        )
        await message.reply_text("What would you like to do?", reply_markup=inline_keyboard)
    else:
        # Only one image, convert directly to PDF
        await create_single_pdf(user_id, user_dir, images)
        await message.reply_document(os.path.join(user_dir, "output.pdf"))

@app.on_message(filters.command("usage"))
async def show_usage(client: Client, message: Message):
    try:
        user_id = str(message.from_user.id)
        db = load_user_db()
        
        if user_id in db["users"]:
            user_data = db["users"][user_id]
            await message.reply_text(
                f"📊 Your Usage Stats:\n\n"
                f"PDFs Created: {user_data['conversions']}\n"
                f"Images Processed: {user_data['images']}\n\n"
                f"Thank you for using the bot!"
            )
        else:
            await message.reply_text("No usage data found. Please use the bot first.")
    except Exception as e:
        await message.reply_text(f"Error getting usage stats: {str(e)}")

@app.on_message(filters.command("clear"))
async def clear_images(client: Client, message: Message):
    user_id = message.from_user.id
    user_dir = get_user_directory(user_id)
    user_id_str = str(user_id)

    # Clear images and PDFs
    if user_id in user_data and user_data[user_id]["images"]:
        # Delete all files in user directory
        for file in os.listdir(user_dir):
            os.remove(os.path.join(user_dir, file))
        # Clear the user's image list
        user_data[user_id]["images"] = []

    # Reset user's usage stats in database
    db = load_user_db()
    if user_id_str in db["users"]:
        db["users"][user_id_str]["conversions"] = 0
        db["users"][user_id_str]["images"] = 0
        save_user_db(db)

    await message.reply_text("All images, PDFs and your usage stats have been cleared.")

@app.on_callback_query()
async def handle_callback_query(client: Client, callback_query):
    user_id = callback_query.from_user.id
    user_dir = get_user_directory(user_id)
    images = user_data[user_id]["images"]

    # Delete the query message
    await callback_query.message.delete()

    if not images and callback_query.data != "clear":
        await callback_query.message.reply_text("No images found. Please send images first.")
        await callback_query.answer()
        return

    if callback_query.data == "specific_image":
        # Show a list of images for the user to select
        keyboard = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton(f"Image {i + 1}", callback_data=f"convert_image_{i}")]
                for i in range(len(images))
            ]
        )
        await callback_query.message.reply_text("Select an image to convert to PDF:", reply_markup=keyboard)
    elif callback_query.data == "all_images":
        # Convert all images to a single PDF
        await create_single_pdf(user_id, user_dir, images)
        await callback_query.message.reply_document(os.path.join(user_dir, "output.pdf"))
    elif callback_query.data.startswith("convert_image_"):
        # Convert the selected image to PDF
        image_index = int(callback_query.data.split("_")[-1])
        selected_image = [images[image_index]]
        await create_single_pdf(user_id, user_dir, selected_image)
        await callback_query.message.reply_document(os.path.join(user_dir, "output.pdf"))
    elif callback_query.data == "clear":
        # Clear all images and PDFs
        if images:
            for file in os.listdir(user_dir):
                os.remove(os.path.join(user_dir, file))
            # Clear the user's image list
            user_data[user_id]["images"] = []
            await callback_query.message.reply_text("All images and PDFs have been cleared.")
        else:
            await callback_query.message.reply_text("All images already cleared.")

    await callback_query.answer()

async def create_single_pdf(user_id, user_dir, images):
    if not images:
        raise ValueError("No images found to create a PDF.")

    pdf_path = os.path.join(user_dir, "output.pdf")
    images_pil = [Image.open(image).convert("RGB") for image in images]
    images_pil[0].save(pdf_path, save_all=True, append_images=images_pil[1:])
    
    # Update conversion stats
    db = load_user_db()
    user_id_str = str(user_id)
    
    # Convert old list format to new dict format if needed
    if isinstance(db["users"], list):
        db["users"] = {str(u): {"conversions": 0, "images": 0} for u in db["users"]}
    
    if user_id_str not in db["users"]:
        db["users"][user_id_str] = {"conversions": 0, "images": 0}
        db["count"] = len(db["users"])
    
    db["users"][user_id_str]["conversions"] += 1
    db["users"][user_id_str]["images"] += len(images)
    db["total_conversions"] += 1
    db["total_images"] += len(images)
    save_user_db(db)

if __name__ == "__main__":
    # Start the Flask server in a separate thread
    flask_thread = Thread(target=run_flask)
    flask_thread.daemon = True  # Daemonize the thread so it exits when the main program exits
    flask_thread.start()

    # Start the bot
    print("Bot is running...")
    app.run()
