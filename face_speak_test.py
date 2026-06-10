import pygame
import subprocess
import threading
import time

pygame.display.init()

screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
pygame.display.set_caption("Robot Face Speak Test")

BLACK = (0, 0, 0)
BLUE = (0, 180, 255)
WHITE = (255, 255, 255)

speaking = True
running = True

def play_audio():
    global speaking
    subprocess.run(["aplay", "-D", "plughw:2,0", "answer.wav"])
    speaking = False

threading.Thread(target=play_audio).start()

while running:
    screen.fill(BLACK)
    width, height = screen.get_size()

    # Eyes
    pygame.draw.ellipse(screen, BLUE, (width * 0.25, height * 0.25, 120, 80))
    pygame.draw.ellipse(screen, BLUE, (width * 0.60, height * 0.25, 120, 80))

    # Mouth
    if speaking and int(time.time() * 5) % 2 == 0:
        pygame.draw.ellipse(screen, WHITE, (width * 0.42, height * 0.60, 160, 80))
    else:
        pygame.draw.arc(screen, WHITE, (width * 0.38, height * 0.58, 220, 120), 3.3, 6.1, 8)

    pygame.display.flip()

    for event in pygame.event.get():
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            running = False

    if not speaking:
        time.sleep(1)
        running = False

pygame.quit()
