import gc
from copy import deepcopy
from pathlib import Path

import psutil
import torch
import pytest
import shutil

from posthoc_ema import PostHocEMA


@pytest.fixture(autouse=True)
def cleanup_checkpoints():
    """Clean up test checkpoints before and after each test."""
    # Cleanup before test
    for path in ["posthoc-ema", "posthoc-ema-diff", "posthoc-ema-all"]:
        if Path(path).exists():
            shutil.rmtree(path)

    yield

    # Cleanup after test
    for path in ["posthoc-ema", "posthoc-ema-diff", "posthoc-ema-all"]:
        if Path(path).exists():
            shutil.rmtree(path)


def test_basic_usage_with_updates(tmp_path: Path):
    """Test the basic usage pattern with model updates."""
    model = torch.nn.Linear(512, 512)
    posthoc_ema = PostHocEMA.from_model(
        model,
        tmp_path / "basic-usage",
        checkpoint_every=5,  # More frequent checkpoints for testing
        sigma_rels=(0.05, 0.28),  # Explicitly set sigma_rels
        update_after_step=0,  # Start immediately to match original behavior
    )

    # Simulate training loop
    for _ in range(10):  # Reduced from 1000 for test speed
        # mutate your network, normally with an optimizer
        with torch.no_grad():
            model.weight.copy_(torch.randn_like(model.weight))
            model.bias.copy_(torch.randn_like(model.bias))
        posthoc_ema.update_(model)

    # Verify we can get predictions
    data = torch.randn(1, 512)
    predictions = model(data)
    assert predictions.shape == (1, 512)


def test_context_manager_helper(tmp_path: Path):
    """Test using the context manager helper for EMA model."""
    model = torch.nn.Linear(512, 512)
    posthoc_ema = PostHocEMA.from_model(
        model,
        tmp_path / "context-manager",
        checkpoint_every=5,  # More frequent checkpoints for testing
        sigma_rels=(0.05, 0.28),  # Explicitly set sigma_rels
        update_after_step=0,  # Start immediately to match original behavior
    )

    # Update enough times to create checkpoints
    for _ in range(10):  # Reduced from 1000 for test speed
        with torch.no_grad():
            model.weight.copy_(torch.randn_like(model.weight))
            model.bias.copy_(torch.randn_like(model.bias))
        posthoc_ema.update_(model)

    data = torch.randn(1, 512)
    predictions = model(data)

    # use the helper
    with posthoc_ema.model(model, sigma_rel=0.15) as ema_model:
        ema_predictions = ema_model(data)
        assert ema_predictions.shape == predictions.shape


def test_manual_cpu_usage(tmp_path: Path):
    """Test manual CPU usage without the context manager."""
    model = torch.nn.Linear(512, 512)
    posthoc_ema = PostHocEMA.from_model(
        model,
        tmp_path / "manual-cpu",
        checkpoint_every=5,  # More frequent checkpoints for testing
        sigma_rels=(0.05, 0.28),  # Explicitly set sigma_rels
        update_after_step=0,  # Start immediately to match original behavior
    )

    # Update enough times to create checkpoints
    for _ in range(10):  # Reduced from 1000 for test speed
        with torch.no_grad():
            model.weight.copy_(torch.randn_like(model.weight))
            model.bias.copy_(torch.randn_like(model.bias))
        posthoc_ema.update_(model)

    data = torch.randn(1, 512)

    # or without magic
    model.cpu()
    with posthoc_ema.state_dict(sigma_rel=0.15) as state_dict:
        ema_model = deepcopy(model)
        ema_model.load_state_dict(state_dict)
        ema_predictions = ema_model(data)
        assert ema_predictions.shape == (1, 512)
        del ema_model


def test_synthesize_after_training(tmp_path: Path):
    """Test synthesizing EMA after training."""
    model = torch.nn.Linear(512, 512)
    checkpoint_dir = tmp_path / "synthesize-after"

    # First create some checkpoints
    posthoc_ema = PostHocEMA.from_model(
        model,
        checkpoint_dir,
        checkpoint_every=5,  # More frequent checkpoints for testing
        sigma_rels=(0.05, 0.28),  # Explicitly set sigma_rels
        update_after_step=0,  # Start immediately to match original behavior
    )
    for _ in range(10):  # Reduced from 1000 for test speed
        with torch.no_grad():
            model.weight.copy_(torch.randn_like(model.weight))
            model.bias.copy_(torch.randn_like(model.bias))
        posthoc_ema.update_(model)

    data = torch.randn(1, 512)

    # Synthesize after training
    posthoc_ema = PostHocEMA.from_path(checkpoint_dir, model)
    with posthoc_ema.model(model, sigma_rel=0.15) as ema_model:
        ema_predictions = ema_model(data)
        assert ema_predictions.shape == (1, 512)


def test_synthesize_without_model(tmp_path: Path):
    """Test synthesizing EMA without model."""
    model = torch.nn.Linear(512, 512)
    checkpoint_dir = tmp_path / "synthesize-without"

    # First create some checkpoints
    posthoc_ema = PostHocEMA.from_model(
        model,
        checkpoint_dir,
        checkpoint_every=5,  # More frequent checkpoints for testing
        sigma_rels=(0.05, 0.28),  # Explicitly set sigma_rels
        update_after_step=0,  # Start immediately to match original behavior
    )
    for _ in range(10):  # Reduced from 1000 for test speed
        with torch.no_grad():
            model.weight.copy_(torch.randn_like(model.weight))
            model.bias.copy_(torch.randn_like(model.bias))
        posthoc_ema.update_(model)

    # Or without model
    posthoc_ema = PostHocEMA.from_path(checkpoint_dir)
    with posthoc_ema.state_dict(sigma_rel=0.15) as state_dict:
        assert isinstance(state_dict, dict)
        assert len(state_dict) > 0


def test_set_parameters_during_training(tmp_path: Path):
    """Test setting parameters to EMA state during training."""
    model = torch.nn.Linear(512, 512)
    checkpoint_dir = tmp_path / "set-params"

    posthoc_ema = PostHocEMA.from_model(
        model,
        checkpoint_dir,
        checkpoint_every=5,  # More frequent checkpoints for testing
        sigma_rels=(0.05, 0.28),  # Explicitly set sigma_rels
        update_after_step=0,  # Start immediately to match original behavior
    )

    # Update enough times to create checkpoints
    for _ in range(10):  # Reduced from 1000 for test speed
        with torch.no_grad():
            model.weight.copy_(torch.randn_like(model.weight))
            model.bias.copy_(torch.randn_like(model.bias))
        posthoc_ema.update_(model)

    # Save original state
    original_state = deepcopy(model.state_dict())

    # Set parameters to EMA state during training
    with posthoc_ema.state_dict(sigma_rel=0.15) as state_dict:
        model.load_state_dict(state_dict, strict=False)
        # Verify state has changed
        assert not torch.allclose(
            model.weight, original_state["weight"].clone().detach()
        )


def test_only_requires_grad_parameters(tmp_path: Path):
    """Test that only parameters with requires_grad=True are included in state dict when only_save_diff=True."""
    # Create a model with some parameters that don't require gradients
    model = torch.nn.Sequential(
        torch.nn.Linear(512, 512),
        torch.nn.BatchNorm1d(512, track_running_stats=True),
        torch.nn.Linear(512, 512),
    )

    # Disable gradients for some parameters
    model[0].bias.requires_grad = False
    model[1].weight.requires_grad = False
    model[1].bias.requires_grad = False

    # Test with only_save_diff=True
    posthoc_ema_diff = PostHocEMA.from_model(
        model,
        tmp_path / "only-grad-diff",
        checkpoint_every=5,
        sigma_rels=(0.05, 0.28),
        only_save_diff=True,
        update_after_step=0,  # Start immediately to match original behavior
    )

    # Test with default (only_save_diff=False)
    posthoc_ema_all = PostHocEMA.from_model(
        model,
        tmp_path / "only-grad-all",
        checkpoint_every=5,
        sigma_rels=(0.05, 0.28),
        update_after_step=0,  # Start immediately to match original behavior
    )

    # Update enough times to create checkpoints
    for _ in range(10):
        with torch.no_grad():
            for param in model.parameters():
                if param.requires_grad:
                    param.copy_(torch.randn_like(param))
        posthoc_ema_diff.update_(model)
        posthoc_ema_all.update_(model)

    # Test only_save_diff=True behavior
    with posthoc_ema_diff.state_dict(sigma_rel=0.15) as state_dict:
        # Check that parameters without requires_grad are not in state dict
        assert "0.bias" not in state_dict
        assert "1.weight" not in state_dict
        assert "1.bias" not in state_dict

        # Check that parameters with requires_grad are in state dict
        assert "0.weight" in state_dict
        assert "2.weight" in state_dict
        assert "2.bias" in state_dict

        # Check that running stats buffers are still included
        assert "1.running_mean" in state_dict
        assert "1.running_var" in state_dict

    # Test default behavior (only_save_diff=False)
    with posthoc_ema_all.state_dict(sigma_rel=0.15) as state_dict:
        # Check that all parameters are in state dict
        assert "0.bias" in state_dict
        assert "1.weight" in state_dict
        assert "1.bias" in state_dict
        assert "0.weight" in state_dict
        assert "2.weight" in state_dict
        assert "2.bias" in state_dict

        # Check that running stats buffers are included
        assert "1.running_mean" in state_dict
        assert "1.running_var" in state_dict

    # Clean up
    for path in ["posthoc-ema-diff", "posthoc-ema-all"]:
        if Path(path).exists():
            for file in Path(path).glob("*"):
                file.unlink()
            Path(path).rmdir()


def test_checkpoint_size_with_requires_grad():
    """Test that checkpoint files are smaller when fewer parameters require gradients."""
    # Create two identical models with larger layers
    model_all_grad = torch.nn.Sequential(
        torch.nn.Linear(1024, 1024),
        torch.nn.BatchNorm1d(1024, track_running_stats=True),
        torch.nn.Linear(1024, 1024),
        torch.nn.BatchNorm1d(1024, track_running_stats=True),
        torch.nn.Linear(1024, 1024),
    )

    model_some_grad = torch.nn.Sequential(
        torch.nn.Linear(1024, 1024),
        torch.nn.BatchNorm1d(1024, track_running_stats=True),
        torch.nn.Linear(1024, 1024),
        torch.nn.BatchNorm1d(1024, track_running_stats=True),
        torch.nn.Linear(1024, 1024),
    )

    # Disable gradients for more parameters in the second model
    model_some_grad[0].bias.requires_grad = False
    model_some_grad[1].weight.requires_grad = False
    model_some_grad[1].bias.requires_grad = False
    model_some_grad[2].bias.requires_grad = False
    model_some_grad[3].weight.requires_grad = False
    model_some_grad[3].bias.requires_grad = False
    model_some_grad[4].bias.requires_grad = False

    # Create EMA instances with same settings
    posthoc_ema_all = PostHocEMA.from_model(
        model_all_grad,
        "posthoc-ema-all",
        checkpoint_every=5,
        sigma_rels=(0.05,),  # Single sigma_rel for simpler comparison
        update_after_step=0,  # Start immediately to match original behavior
    )

    posthoc_ema_some = PostHocEMA.from_model(
        model_some_grad,
        "posthoc-ema-some",
        checkpoint_every=5,
        sigma_rels=(0.05,),  # Single sigma_rel for simpler comparison
        only_save_diff=True,  # Only save parameters with requires_grad=True
        update_after_step=0,  # Start immediately to match original behavior
    )

    # Update both models with same random values
    for _ in range(10):
        with torch.no_grad():
            # Update all parameters with random values
            for param_all, param_some in zip(
                model_all_grad.parameters(), model_some_grad.parameters()
            ):
                if (
                    param_some.requires_grad
                ):  # Only update parameters that require gradients
                    rand_values = torch.randn_like(param_all)
                    param_all.copy_(rand_values)
                    param_some.copy_(rand_values)

        posthoc_ema_all.update_(model_all_grad)
        posthoc_ema_some.update_(model_some_grad)

    # Get file sizes
    all_grad_files = sorted(Path("posthoc-ema-all").glob("*.pt"))
    some_grad_files = sorted(Path("posthoc-ema-some").glob("*.pt"))

    # Compare sizes of corresponding checkpoints
    for all_file, some_file in zip(all_grad_files, some_grad_files):
        all_size = all_file.stat().st_size
        some_size = some_file.stat().st_size

        # The checkpoint with fewer requires_grad parameters should be smaller
        assert some_size < all_size, (
            f"Expected checkpoint with fewer requires_grad parameters to be smaller. "
            f"All grad size: {all_size}, Some grad size: {some_size}"
        )

    # Clean up
    for path in ["posthoc-ema-all", "posthoc-ema-some"]:
        if Path(path).exists():
            for file in Path(path).glob("*"):
                file.unlink()
            Path(path).rmdir()


def test_ram_usage_with_requires_grad():
    """Test that RAM usage is lower when fewer parameters require gradients."""

    def get_ram_usage():
        """Get current RAM usage in MB."""
        process = psutil.Process()
        return process.memory_info().rss / 1024 / 1024

    # Force garbage collection and get initial memory state
    gc.collect()
    initial_ram = get_ram_usage()
    print(f"\nInitial RAM usage: {initial_ram:.2f}MB")

    # Create two identical models with larger layers
    model_all_grad = torch.nn.Sequential(
        torch.nn.Linear(2048, 2048),
        torch.nn.BatchNorm1d(2048, track_running_stats=True),
        torch.nn.Linear(2048, 2048),
        torch.nn.BatchNorm1d(2048, track_running_stats=True),
        torch.nn.Linear(2048, 2048),
    )

    model_some_grad = torch.nn.Sequential(
        torch.nn.Linear(2048, 2048),
        torch.nn.BatchNorm1d(2048, track_running_stats=True),
        torch.nn.Linear(2048, 2048),
        torch.nn.BatchNorm1d(2048, track_running_stats=True),
        torch.nn.Linear(2048, 2048),
    )

    # Disable gradients for more parameters in the second model
    model_some_grad[0].bias.requires_grad = False
    model_some_grad[1].weight.requires_grad = False
    model_some_grad[1].bias.requires_grad = False
    model_some_grad[2].bias.requires_grad = False
    model_some_grad[3].weight.requires_grad = False
    model_some_grad[3].bias.requires_grad = False
    model_some_grad[4].bias.requires_grad = False

    # Create EMA instances with same settings
    posthoc_ema_all = PostHocEMA.from_model(
        model_all_grad,
        "posthoc-ema-all",
        checkpoint_every=5,
        sigma_rels=(0.05,),  # Single sigma_rel for simpler comparison
        update_after_step=0,  # Start immediately to match original behavior
    )

    # Force garbage collection and get memory after first model
    gc.collect()
    ram_with_all_grad = get_ram_usage()
    print(f"\nRAM usage with all requires_grad: {ram_with_all_grad:.2f}MB")
    print(f"Increase from initial: {ram_with_all_grad - initial_ram:.2f}MB")

    # Delete first model and EMA
    del model_all_grad
    del posthoc_ema_all
    gc.collect()

    # Create second EMA instance
    posthoc_ema_some = PostHocEMA.from_model(
        model_some_grad,
        "posthoc-ema-some",
        checkpoint_every=5,
        sigma_rels=(0.05,),  # Single sigma_rel for simpler comparison
        update_after_step=0,  # Start immediately to match original behavior
    )

    # Force garbage collection and get memory after second model
    gc.collect()
    ram_with_some_grad = get_ram_usage()
    print(f"\nRAM usage with some requires_grad: {ram_with_some_grad:.2f}MB")
    print(f"Increase from initial: {ram_with_some_grad - initial_ram:.2f}MB")

    # The model with fewer requires_grad parameters should use less RAM
    ram_diff = ram_with_all_grad - ram_with_some_grad
    print(f"\nRAM difference: {ram_diff:.2f}MB")
    assert ram_diff > 0, (
        f"Expected lower RAM usage with fewer requires_grad parameters. "
        f"Difference: {ram_diff:.2f}MB"
    )

    # Clean up
    for path in ["posthoc-ema-all", "posthoc-ema-some"]:
        if Path(path).exists():
            for file in Path(path).glob("*"):
                file.unlink()
            Path(path).rmdir()


def test_save_full_weights():
    """Test that all weights are saved when only_save_diff=False, regardless of requires_grad."""
    # Create a model with some parameters that don't require gradients
    model = torch.nn.Sequential(
        torch.nn.Linear(512, 512),
        torch.nn.BatchNorm1d(512, track_running_stats=True),
        torch.nn.Linear(512, 512),
    )

    # Disable gradients for some parameters and set specific values
    with torch.no_grad():
        model[0].bias.requires_grad = False
        model[0].bias.fill_(1.0)  # Set a known value

        model[1].weight.requires_grad = False
        model[1].weight.fill_(2.0)  # Set a known value
        model[1].bias.requires_grad = False
        model[1].bias.fill_(3.0)  # Set a known value

    # Create EMA instance with only_save_diff=False
    posthoc_ema = PostHocEMA.from_model(
        model,
        "posthoc-ema",
        checkpoint_every=5,
        sigma_rels=(0.05,),
        only_save_diff=False,  # Save all parameters
        update_after_step=0,  # Start immediately to match original behavior
    )

    # Update enough times to create checkpoints
    for _ in range(10):
        with torch.no_grad():
            # Only update parameters that require gradients
            for param in model.parameters():
                if param.requires_grad:
                    param.copy_(torch.randn_like(param))
        posthoc_ema.update_(model)

    # Load the checkpoint and verify all parameters are present with correct values
    with posthoc_ema.state_dict(sigma_rel=0.05) as state_dict:
        # Check that all parameters are in state dict
        assert "0.bias" in state_dict
        assert "1.weight" in state_dict
        assert "1.bias" in state_dict

        # Check that parameters without gradients have their original values
        assert torch.allclose(
            state_dict["0.bias"].to(model[0].bias.dtype),
            torch.full_like(model[0].bias, 1.0),
        )
        assert torch.allclose(
            state_dict["1.weight"].to(model[1].weight.dtype),
            torch.full_like(model[1].weight, 2.0),
        )
        assert torch.allclose(
            state_dict["1.bias"].to(model[1].bias.dtype),
            torch.full_like(model[1].bias, 3.0),
        )

        # Check that running stats buffers are included
        assert "1.running_mean" in state_dict
        assert "1.running_var" in state_dict

    # Clean up
    if Path("posthoc-ema").exists():
        for file in Path("posthoc-ema").glob("*"):
            file.unlink()
        Path("posthoc-ema").rmdir()


def test_checkpoint_dtype():
    """Test that checkpoint dtype is respected and defaults to original dtype."""
    # Create a model with mixed dtypes
    model = torch.nn.Sequential(
        torch.nn.Linear(512, 512),  # Default is float32
        torch.nn.BatchNorm1d(512, track_running_stats=True),
    )

    # Convert some parameters to float64
    model[0].weight.data = model[0].weight.data.to(torch.float64)
    model[0].bias.data = model[0].bias.data.to(torch.float64)

    # Test default behavior (preserve original dtypes)
    posthoc_ema_default = PostHocEMA.from_model(
        model,
        "posthoc-ema-default",
        checkpoint_every=5,
        sigma_rels=(0.05,),
        update_after_step=0,  # Start immediately to match original behavior
    )

    # Test with specified dtype (bfloat16)
    posthoc_ema_bfloat16 = PostHocEMA.from_model(
        model,
        "posthoc-ema-bfloat16",
        checkpoint_every=5,
        sigma_rels=(0.05,),
        checkpoint_dtype=torch.bfloat16,
        update_after_step=0,  # Start immediately to match original behavior
    )

    # Update both models
    for _ in range(10):
        with torch.no_grad():
            model[0].weight.copy_(torch.randn_like(model[0].weight))
            model[0].bias.copy_(torch.randn_like(model[0].bias))
        posthoc_ema_default.update_(model)
        posthoc_ema_bfloat16.update_(model)

    # Test default behavior (preserve original dtypes)
    with posthoc_ema_default.state_dict(sigma_rel=0.05) as state_dict:
        # Linear layer parameters should be float64
        assert state_dict["0.weight"].dtype == torch.float64
        assert state_dict["0.bias"].dtype == torch.float64
        # BatchNorm parameters should be float32
        assert state_dict["1.weight"].dtype == torch.float32
        assert state_dict["1.bias"].dtype == torch.float32
        assert state_dict["1.running_mean"].dtype == torch.float32
        assert state_dict["1.running_var"].dtype == torch.float32

    # Test bfloat16 behavior
    with posthoc_ema_bfloat16.state_dict(sigma_rel=0.05) as state_dict:
        # All parameters should be bfloat16
        assert state_dict["0.weight"].dtype == torch.bfloat16
        assert state_dict["0.bias"].dtype == torch.bfloat16
        assert state_dict["1.weight"].dtype == torch.bfloat16
        assert state_dict["1.bias"].dtype == torch.bfloat16
        assert state_dict["1.running_mean"].dtype == torch.bfloat16
        assert state_dict["1.running_var"].dtype == torch.bfloat16

    # Clean up
    for path in ["posthoc-ema-default", "posthoc-ema-bfloat16"]:
        if Path(path).exists():
            for file in Path(path).glob("*"):
                file.unlink()
            Path(path).rmdir()


def test_context_manager_with_only_save_diff():
    """Test that context manager works correctly with only_save_diff=True."""
    # Create a model with some parameters that don't require gradients
    model = torch.nn.Sequential(
        torch.nn.Linear(512, 512),
        torch.nn.BatchNorm1d(512, track_running_stats=True),
        torch.nn.Linear(512, 512),
    )

    # Disable gradients for some parameters
    model[0].bias.requires_grad = False
    model[1].weight.requires_grad = False
    model[1].bias.requires_grad = False

    # Create EMA instance with only_save_diff=True
    posthoc_ema = PostHocEMA.from_model(
        model,
        "posthoc-ema",
        checkpoint_every=5,
        sigma_rels=(0.05,),
        only_save_diff=True,  # Only save parameters with requires_grad=True
        update_after_step=0,  # Start immediately to match original behavior
    )

    # Update enough times to create checkpoints
    for _ in range(10):
        with torch.no_grad():
            # Only update parameters that require gradients
            for param in model.parameters():
                if param.requires_grad:
                    param.copy_(torch.randn_like(param))
        posthoc_ema.update_(model)

    # This should work without errors despite missing parameters in state dict
    with posthoc_ema.model(model, sigma_rel=0.05) as ema_model:
        x = torch.randn(1, 512)
        output = ema_model(x)
        assert output.shape == (1, 512)

    # Clean up
    if Path("posthoc-ema").exists():
        for file in Path("posthoc-ema").glob("*"):
            file.unlink()
        Path("posthoc-ema").rmdir()


def test_calculation_dtype():
    """Test that synthesis calculations use specified calculation_dtype."""
    # Create a model with mixed dtypes
    model = torch.nn.Sequential(
        torch.nn.Linear(512, 512),  # Default is float32
        torch.nn.BatchNorm1d(512, track_running_stats=True),
    )

    # Convert model to float16
    model = model.to(torch.float16)

    # Create EMA instance
    posthoc_ema = PostHocEMA.from_model(
        model,
        "posthoc-ema",
        checkpoint_every=5,
        sigma_rels=(0.05,),
        update_after_step=0,  # Start immediately to match original behavior
    )

    # Update model
    for _ in range(10):
        with torch.no_grad():
            model[0].weight.copy_(torch.randn_like(model[0].weight))
            model[0].bias.copy_(torch.randn_like(model[0].bias))
        posthoc_ema.update_(model)

    # Test default behavior (float32 calculations, float16 output)
    with posthoc_ema.state_dict(sigma_rel=0.05) as state_dict:
        # All parameters should be float16 (original dtype)
        assert state_dict["0.weight"].dtype == torch.float16
        assert state_dict["0.bias"].dtype == torch.float16
        assert state_dict["1.weight"].dtype == torch.float16
        assert state_dict["1.bias"].dtype == torch.float16
        assert state_dict["1.running_mean"].dtype == torch.float16
        assert state_dict["1.running_var"].dtype == torch.float16

    # Test float64 behavior
    with posthoc_ema.state_dict(
        sigma_rel=0.05, calculation_dtype=torch.float64
    ) as state_dict:
        # All parameters should still be float16 (original dtype)
        assert state_dict["0.weight"].dtype == torch.float16
        assert state_dict["0.bias"].dtype == torch.float16
        assert state_dict["1.weight"].dtype == torch.float16
        assert state_dict["1.bias"].dtype == torch.float16
        assert state_dict["1.running_mean"].dtype == torch.float16
        assert state_dict["1.running_var"].dtype == torch.float16

    # Clean up
    if Path("posthoc-ema").exists():
        for file in Path("posthoc-ema").glob("*"):
            file.unlink()
        Path("posthoc-ema").rmdir()


def test_from_model_with_existing_checkpoints():
    """Test that from_model raises an error when checkpoints exist."""
    # Create a simple model
    model = torch.nn.Linear(10, 10)

    # Create initial EMA instance and some checkpoints
    checkpoint_dir = Path("test-checkpoints")
    posthoc_ema = PostHocEMA.from_model(
        model=model,
        checkpoint_dir=checkpoint_dir,
        max_checkpoints=2,
        update_every=1,
        checkpoint_every=1,
        update_after_step=0,  # Start immediately to match original behavior
    )

    # Create a checkpoint
    posthoc_ema.update_(model)

    # Try to create another instance with from_model
    with pytest.raises(ValueError, match="already contains checkpoints"):
        PostHocEMA.from_model(
            model=model,
            checkpoint_dir=checkpoint_dir,
        )

    # Clean up
    if checkpoint_dir.exists():
        for file in checkpoint_dir.glob("*"):
            file.unlink()
        checkpoint_dir.rmdir()
