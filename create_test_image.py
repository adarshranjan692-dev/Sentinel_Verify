"""
Create a test image with text for OCR testing
"""
from PIL import Image, ImageDraw, ImageFont
import os

# Create a new image with white background
width, height = 400, 300
image = Image.new('RGB', (width, height), color='white')
draw = ImageDraw.Draw(image)

# Add text to the image
text_lines = [
    "PASSPORT NUMBER: AB123456",
    "NAME: JOHN SMITH",
    "DATE OF BIRTH: 1990-05-15",
    "NATIONALITY: UNITED STATES",
    "EXPIRY DATE: 2030-06-20"
]

# Try to use a system font, fall back to default if not available
try:
    # Try common Windows font paths
    font = ImageFont.truetype("C:\\Windows\\Fonts\\arial.ttf", 20)
except:
    # Fall back to default font
    font = ImageFont.load_default()

# Draw text
y_position = 30
for line in text_lines:
    draw.text((30, y_position), line, fill='black', font=font)
    y_position += 40

# Save the image
output_path = os.path.join(os.path.dirname(__file__), "uploads", "test_ocr_image.png")
os.makedirs(os.path.dirname(output_path), exist_ok=True)
image.save(output_path)
print(f"✅ Test image created: {output_path}")
print(f"   Image size: {width}x{height}")
print(f"   Text content: Passport information sample")
