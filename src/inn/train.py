import csv

import numpy as np
import torch
from torch import nn
from torch.optim import Adam
from torch.optim.lr_scheduler import ReduceLROnPlateau
from torch.utils.data import DataLoader, random_split

from dataset import load_dataset
from model import create_inn
import mmd


# factors for the loss terms
FORWARD_FIT_FACTOR = 1
FORWARD_MMD_FACTOR = 50
BACKWARD_MMD_FACTOR = 500
RECONSTRUCTION_FACTOR = 1


def loss_forward_mmd(positions_pred: torch.tensor, positions: torch.tensor, position_dim: int, z_dim: int):
    # Shorten output, and remove gradients wrt y, for latent loss
    output_block_grad = torch.cat((positions_pred[:, :z_dim], positions_pred[:, -position_dim:].data), dim=1)
    y_short = torch.cat((positions[:, :z_dim], positions[:, -position_dim:]), dim=1)

    l_forward_fit = FORWARD_FIT_FACTOR * mmd.l2_fit(positions_pred[:, z_dim:], positions[:, z_dim:])
    l_forward_mmd = FORWARD_MMD_FACTOR * torch.mean(mmd.forward_mmd(output_block_grad, y_short))

    return l_forward_fit, l_forward_mmd


def loss_backward_mmd(priors: torch.tensor, positions: torch.tensor, inn: nn.Module):
    # TODO use jac=False ?
    priors_pred, _ = inn(positions, rev=True)
    backward_mmd = mmd.backward_mmd(priors, priors_pred)
    return BACKWARD_MMD_FACTOR * torch.mean(backward_mmd)


def loss_reconstruction(positions_pred: torch.tensor, priors: torch.tensor, inn: nn.Module, position_dim: int, z_dim: int):
    cat_inputs = [positions_pred[:, :z_dim], positions_pred[:, -position_dim:]]
    # TODO use jac=False ?
    x_reconstructed, _ = inn(torch.cat(cat_inputs, 1), rev=True)
    return RECONSTRUCTION_FACTOR * mmd.l2_fit(x_reconstructed, priors)


def train(
    batch_size: int = 128,
    lr: float = 1e-6,
    epochs: int = 10000000,
    lr_scheduler_patience: int = 10,
    val_set_portion: float = 0.1,  # portion of the dataset that will be used for validation
    log_file: str = "losses.csv",
):
    # prepare dataset
    dataset, priors_dim, position_dim = load_dataset()
    z_dim = priors_dim - position_dim
    val_set_size = int(len(dataset) * val_set_portion)
    train_dataset, val_dataset = random_split(dataset, [len(dataset) - val_set_size, val_set_size])
    train_loader = DataLoader(train_dataset, batch_size, shuffle=True, num_workers=2, drop_last=True)
    val_loader = DataLoader(val_dataset, batch_size, shuffle=True, num_workers=2, drop_last=True)

    inn = create_inn(priors_dim)
    optimizer = Adam(inn.parameters(), lr=lr)
    lr_scheduler = ReduceLROnPlateau(optimizer, patience=lr_scheduler_patience, verbose=True)

    for epoch in range(epochs):

        # Training
        ###########

        train_loss_history = []
        inn.train()

        for priors, positions in train_loader:
            noise_batch = torch.randn(batch_size, z_dim)
            positions = torch.cat((noise_batch, positions), dim=1)

            # TODO use jac=False ?
            positions_pred, _ = inn(priors)

            batch_losses = []
            batch_losses.extend(loss_forward_mmd(positions_pred, positions, position_dim, z_dim))
            batch_losses.append(loss_backward_mmd(priors, positions, inn))
            batch_losses.append(loss_reconstruction(positions_pred.data, priors, inn, position_dim, z_dim))

            train_loss_history.append([batch_loss.item() for batch_loss in batch_losses])

            total_batch_loss = sum(batch_losses)
            total_batch_loss.backward()
            optimizer.step()

        train_loss_mean = np.mean(train_loss_history, axis=0)
        lr_scheduler.step(np.mean(train_loss_mean))
        print(f"[Epoch {epoch}] Train loss: {np.mean(train_loss_mean)}, {train_loss_mean}")

        # Validation
        #############

        val_loss_history = []
        inn.eval()

        with torch.no_grad():
            for priors, positions in val_loader:
                noise_batch = torch.randn(batch_size, z_dim)
                positions = torch.cat((noise_batch, positions), dim=1)

                # TODO use jac=False ?
                positions_pred, _ = inn(priors)

                batch_losses = []
                batch_losses.extend(loss_forward_mmd(positions_pred, positions, position_dim, z_dim))
                batch_losses.append(loss_backward_mmd(priors, positions, inn))
                batch_losses.append(loss_reconstruction(positions_pred.data, priors, inn, position_dim, z_dim))

                val_loss_history.append([batch_loss.item() for batch_loss in batch_losses])

        val_loss_mean = np.mean(val_loss_history, axis=0)
        print(f"[Epoch {epoch}] Val loss:   {np.mean(val_loss_mean)}, {val_loss_mean}")

        # log losses
        with open(log_file, 'a+', newline='') as file:
            csv.writer(file).writerow([np.mean(train_loss_mean), np.mean(val_loss_mean)])


if __name__ == "__main__":
    train()
