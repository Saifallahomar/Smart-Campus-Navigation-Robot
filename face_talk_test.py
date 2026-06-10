import pygame
import time

pygame.init()

screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
pygame.display.set_caption("Robot Talking Face")

BLACK = (0, 0, 0)
BLUE = (0, 180, 255)
WHITE = (255, 255, 255)

clock = pygame.time.Clock()
talking = True
mouth_open = False

start_time = time.time()

running = True
while running:
    screen.fill(BLACK)
    width, height = screen.get_size()

    # Eyes
    pygame.draw.ellipse(screen, BLUE, (width * 0.25, height * 0.25, 120, 80))
    pygame.draw.ellipse(screen, BLUE, (width * 0.60, height * 0.25, 120, 80))

    # Mouth animation
    if mouth_open:
        pygame.draw.ellipse(screen, WHITE, (width * 0.42, height * 0.60, 160, 80))
    else:
        pygame.draw.arc(screen, WHITE, (width * 0.38, height * 0.58, 220, 120), 3.3, 6.1, 8)

    pygame.display.flip()

    # Change mouth every 0.2 seconds
    mouth_open = not mouth_open
    time.sleep(0.2)

    # Stop talking animation after 5 seconds
    if time.time() - start_time > 5:
        mouth_open = False

    for event in pygame.event.get():
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            running = False

    clock.tick(30)

pygame.quit()
