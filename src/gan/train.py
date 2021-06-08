import os
import torch
import numpy as np
import random
from kinematics.robot_arm_2d_torch import RobotArm2d
from torch.utils.data import DataLoader
from gan.dataset import InverseDataset2d
from gan.model import Generator, Discriminator
from tqdm import tqdm
import wandb


# Configuration
config = dict(
    seed=123456,
    lr=5e-4,
    n_discriminator=5,
    num_epochs=300,
    sample_interval=100,
    save_model_interval=200,
    batch_size=64,
    num_thetas=4,
    dim_pos=2,
    latent_dim=3,
    pos_test=[1.5, 0]
)
# TODO: decide if saving every n epochs or every m samples or batches

# Set random seeds
seed = config["seed"]
torch.backends.cudnn.deterministic = True
random.seed(seed)
np.random.seed(seed)
torch.manual_seed(seed)
torch.cuda.manual_seed_all(seed)
# Device configuration
device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")

# Setup wandb for model tracking
wandb.init(
    project="pytorch-test",
    name="test_full_data_100_1000",
    tags=["playground"],
    config=config
)
# Rename for easier access
config = wandb.config

dataloader = DataLoader(
    InverseDataset2d(
        path="data/inverse.pickle"
    ),
    batch_size=config.batch_size,
    shuffle=True,
    drop_last=True
)


def train():
    generator = Generator(num_thetas=config.num_thetas, dim_pos=config.dim_pos, latent_dim=config.latent_dim)
    discriminator = Discriminator(num_thetas=config.num_thetas, dim_pos=config.dim_pos)
    adversarial_loss = torch.nn.MSELoss()

    # Print model to log structure
    print(generator)
    print(discriminator)

    cuda = True if torch.cuda.is_available() else False
    if cuda:
        generator.cuda()
        discriminator.cuda()
        adversarial_loss.cuda()

    # Optimizer
    optimizer_G = torch.optim.RMSprop(generator.parameters(), lr=config.lr)
    optimizer_D = torch.optim.RMSprop(discriminator.parameters(), lr=config.lr)

    # Log models
    wandb.watch(generator, optimizer_G, log="all", log_freq=10)  # , log_freq=100
    wandb.watch(discriminator, optimizer_D, log="all", log_freq=10)

    Tensor = torch.cuda.FloatTensor if cuda else torch.FloatTensor
    batches_done = 0
    arm = RobotArm2d()
    for epoch in tqdm(range(config.num_epochs)):
        for iter, (thetas_real, pos_real) in enumerate(dataloader):

            # Adversarial ground truths
            valid = Tensor(config.batch_size, 1).fill_(1.0)
            fake = Tensor(config.batch_size, 1).fill_(0.0)

            # Train Generator
            # ---------------------
            optimizer_G.zero_grad()

            # Sample noise as generator input
            z = Tensor(np.random.normal(0, 1, (config.batch_size, config.latent_dim)))
            # Generation of positions can be a random position that can be achieved using forward kinematics of random input
            pos_gen = arm.forward(arm.sample_priors(config.batch_size))

            # Generate batch of thetas
            thetas_gen = generator(z, pos_gen)

            # Calculate loss
            validity = discriminator(thetas_gen, pos_gen)
            loss_G = adversarial_loss(validity, valid)

            loss_G.backward()
            optimizer_G.step()

            # Train Discriminator
            # ---------------------
            optimizer_D.zero_grad()

            # Loss for real thetas
            validity_real = discriminator(thetas_real, pos_real)
            loss_D_real = adversarial_loss(validity_real, valid)

            # Loss for generated (fake) thetas
            # Detach to backpropagate not through entire graph(G+D), but only D
            validity_fake = discriminator(thetas_gen.detach(), pos_gen)
            loss_D_fake = adversarial_loss(validity_fake, fake)

            # Total discriminator loss
            loss_D = (loss_D_real + loss_D_fake) / 2
            loss_D.backward()
            optimizer_D.step()
            batches_done += 1

            # Test the generator, visualize and calculate mean distance
            if batches_done % config.sample_interval == 0:
                # Tensor size (batch_size, 2) with always the same target position
                pos_test = torch.full_like(pos_real, fill_value=config.pos_test[0])
                pos_test[:, 1] = config.pos_test[1]
                # Generate test batch, all to same target position
                generated_test_batch = generator(z, pos_test).detach()
                arm.viz_inverse(pos_test, generated_test_batch, fig_name=f"{batches_done}")
                # TODO: improve image logging, perhaps return fig from inverse?
                # TODO: log all visualizations in the same dir? Create gif?
                mean_euclidean = arm.distance_euclidean(pos_test, arm.forward(generated_test_batch))
                wandb.log({
                    "plot": wandb.Image(os.path.join(arm.viz_dir, f"{batches_done}.png")),
                    "generated_batch": generated_test_batch,
                    "mean_euclidean": mean_euclidean
                })
                print(f"Epoch: {epoch}/{config.num_epochs} | Batch: {iter + 1}/{len(dataloader)} | D loss: {loss_D.item()} | G loss: {loss_G.item()}")

            # TODO: add a euclidean for pairwise distance and not only all to one
            wandb.log({
                "Epoch": epoch,
                "loss_D": loss_D,
                "loss_D_real": loss_D_real,
                "loss_D_fake": loss_D_fake,
                "loss_G": loss_G
            })

            # Save checkpoints
            if batches_done % config.save_model_interval == 0:
                checkpoint = {
                    "epoch": epoch,
                    "generator": generator.state_dict(),
                    "optimizer_G": optimizer_G.state_dict(),
                    "loss_G": loss_G,
                    "discriminator": discriminator.state_dict(),
                    "optimizer_D": optimizer_D.state_dict(),
                    "loss_G": loss_G,
                    "loss_D": loss_D,
                    "loss_D_real": loss_D_real,
                    "loss_D_fake": loss_D_fake
                }
                log_path = os.path.join(wandb.run.dir, "checkpoints")
                os.makedirs(log_path, exist_ok=True)
                torch.save(checkpoint, os.path.join(log_path,  f"{epoch}_checkpoint.pth"))
                # wandb.save(os.path.join(log_path, f"{epoch}_checkpoint.pth"))
                print(f"{epoch} epoch: saved model")

    # Save checkpoint of last epoch
    checkpoint = {
        "epoch": epoch,
        "generator": generator.state_dict(),
        "optimizer_G": optimizer_G.state_dict(),
        "loss_G": loss_G,
        "discriminator": discriminator.state_dict(),
        "optimizer_D": optimizer_D.state_dict(),
        "loss_G": loss_G,
        "loss_D": loss_D,
        "loss_D_real": loss_D_real,
        "loss_D_fake": loss_D_fake
    }
    log_path = os.path.join(wandb.run.dir, "checkpoints")
    os.makedirs(log_path, exist_ok=True)
    # TODO: investigate difference of saving file in wandb dir with torch vs wandb
    torch.save(checkpoint, os.path.join(log_path,  f"{epoch}_checkpoint.pth"))
    # wandb.save(os.path.join(log_path, f"{epoch}_checkpoint.pth"))
    print(f"{epoch} epoch: saved model")
