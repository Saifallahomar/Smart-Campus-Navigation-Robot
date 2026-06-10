import pygame

pygame.init()

screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
pygame.display.set_caption("Robot Face")

BLACK = (0, 0, 0)
BLUE = (0, 180, 255)
WHITE = (255, 255, 255)

running = True

while running:
    screen.fill(BLACK)

    width, height = screen.get_size()

    # Eyes
    pygame.draw.ellipse(screen, BLUE, (width * 0.25, height * 0.25, 120, 80))
    pygame.draw.ellipse(screen, BLUE, (width * 0.60, height * 0.25, 120, 80))

    # Mouth
    pygame.draw.arc(screen, WHITE, (width * 0.38, height * 0.58, 220, 120), 3.3, 6.1, 8)

    pygame.display.flip()

    for event in pygame.event.get():
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                running = False

pygame.quit()
