"""
Génération de la card visuelle (style commentaire) et incrustation
en haut/centre de la vidéo pendant 8 secondes.
"""
import logging
import subprocess
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)


def render_comment_card(text: str, output_image_path: Path) -> Path:
    """
    Génère l'image de la card (via Pillow) au style commentaire premium.
    Retourne le chemin de l'image générée.
    """
    output_image_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Dimensions de la card
    card_width = 800
    padding = 30
    
    # Tentative de chargement d'une police système propre, sinon fallback
    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    try:
        font_user = ImageFont.truetype(font_path, 22)
        font_text = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 20)
        font_meta = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 16)
    except Exception:
        # Fallback pour Pillow >= 10.0.0
        font_user = ImageFont.load_default(size=22)
        font_text = ImageFont.load_default(size=20)
        font_meta = ImageFont.load_default(size=16)

    # Découpage du texte en lignes (wrapping)
    max_text_width = card_width - (padding * 2)
    
    def wrap_text(t, font, max_w):
        lines = []
        words = t.split()
        current_line = []
        for word in words:
            current_line.append(word)
            line_str = " ".join(current_line)
            # Calculer la largeur de la ligne
            bbox = font.getbbox(line_str)
            w = bbox[2] - bbox[0]
            if w > max_w:
                current_line.pop()
                lines.append(" ".join(current_line))
                current_line = [word]
        if current_line:
            lines.append(" ".join(current_line))
        return lines

    text_lines = wrap_text(text, font_text, max_text_width)
    
    # Calcul de la hauteur dynamique de la carte
    line_height = 28
    text_height = len(text_lines) * line_height
    avatar_height = 60
    meta_height = 30
    card_height = padding + avatar_height + 15 + text_height + 15 + meta_height + padding
    
    # Créer l'image avec fond transparent
    img = Image.new("RGBA", (card_width, card_height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # Dessiner le fond de la carte (blanc pur avec coins arrondis et bordure fine)
    draw.rounded_rectangle(
        [(0, 0), (card_width - 1, card_height - 1)],
        radius=20,
        fill=(255, 255, 255, 255),
        outline=(220, 225, 230, 255),
        width=2
    )
    
    # Dessiner l'avatar de l'utilisateur (cercle de couleur avec lettre "S")
    avatar_x = padding
    avatar_y = padding
    draw.ellipse(
        [(avatar_x, avatar_y), (avatar_x + 50, avatar_y + 50)],
        fill=(255, 100, 50, 255)  # Orange type Reddit/Tiktok
    )
    
    # Texte sur l'avatar (lettre "S" au centre)
    avatar_letter = "S"
    let_bbox = font_user.getbbox(avatar_letter)
    let_w = let_bbox[2] - let_bbox[0]
    let_h = let_bbox[3] - let_bbox[1]
    draw.text(
        (avatar_x + (50 - let_w) / 2, avatar_y + (50 - let_h) / 2 - 2),
        avatar_letter,
        font=font_user,
        fill=(255, 255, 255, 255)
    )
    
    # Nom d'utilisateur et date de publication
    username = "StoryTimeBot"
    time_ago = " • il y a 2h"
    draw.text((avatar_x + 65, avatar_y + 4), username, font=font_user, fill=(30, 35, 40, 255))
    
    user_bbox = font_user.getbbox(username)
    draw.text(
        (avatar_x + 65 + (user_bbox[2] - user_bbox[0]), avatar_y + 9),
        time_ago,
        font=font_meta,
        fill=(140, 150, 160, 255)
    )
    
    # Dessiner le corps du texte
    text_y = avatar_y + 50 + 15
    for i, line in enumerate(text_lines):
        draw.text(
            (padding, text_y + (i * line_height)),
            line,
            font=font_text,
            fill=(40, 45, 50, 255)
        )
        
    # Dessiner les éléments de bas de page (Likes & Réponses fictives pour faire vrai)
    meta_y = text_y + text_height + 15
    draw.text((padding, meta_y), "❤️ 12.8k", font=font_meta, fill=(100, 110, 120, 255))
    draw.text((padding + 120, meta_y), "💬 245", font=font_meta, fill=(100, 110, 120, 255))
    draw.text((padding + 220, meta_y), "🔗 Partager", font=font_meta, fill=(100, 110, 120, 255))
    
    img.save(output_image_path, "PNG")
    logger.info(f"Image de la carte commentaire enregistrée : {output_image_path}")
    return output_image_path


def overlay_card_on_video(
    video_path: Path,
    card_image_path: Path,
    duration_sec: int,
    output_path: Path,
    audio_path: Path | None = None,
) -> Path:
    """
    Incruste la card en haut/centre de `video_path` pendant `duration_sec`.
    Si `audio_path` est fourni, il remplace la bande-son de la vidéo finale
    et calibre la durée totale de la vidéo sur celle de l'audio.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Option d'overlay (position x centrée, y à 250px du haut, affiché de t=0 à t=duration_sec)
    filter_complex = f"[0:v][1:v]overlay=(W-w)/2:250:enable='between(t,0,{duration_sec})'[outv]"
    
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-i", str(card_image_path),
    ]
    
    if audio_path:
        cmd.extend(["-i", str(audio_path)])
        
    cmd.extend(["-filter_complex", filter_complex])
    
    # Mapper la vidéo issue du filtre complexe
    cmd.extend(["-map", "[outv]"])
    
    if audio_path:
        # Mapper la piste audio de la voix off
        cmd.extend(["-map", "2:a"])
    else:
        # Mapper la piste audio originale (si elle existe)
        cmd.extend(["-map", "0:a?"])
        
    cmd.extend([
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-pix_fmt", "yuv420p"
    ])
    
    if audio_path:
        cmd.extend([
            "-c:a", "aac",
            "-b:a", "128k",
            "-shortest"  # Aligne la durée de la vidéo sur le fichier audio (le plus court)
        ])
        
    cmd.append(str(output_path))
    
    logger.info(
        f"Incrustation de la carte sur la vidéo. Source: {video_path.name}, "
        f"Audio: {audio_path.name if audio_path else 'original'}, Sortie: {output_path.name}"
    )
    
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    
    if result.returncode != 0:
        logger.error(f"Ffmpeg overlay error logs: {result.stderr}")
        raise RuntimeError(f"Échec de l'incrustation ffmpeg (code {result.returncode}) : {result.stderr[:400]}")
        
    return output_path
