namespace SuperHeroMod.Core;

public static class GameplayMath
{
    public static float ClampFinite(float value, float min, float max, float fallback = 1f)
    {
        if (float.IsNaN(value) || float.IsInfinity(value)) return fallback;
        return Math.Clamp(value, min, max);
    }

    public static float MultiplyAndClamp(float baseline, float multiplier, float min, float max)
    {
        multiplier = ClampFinite(multiplier, 0f, 2f);
        return Math.Clamp(baseline * multiplier, min, max);
    }

    public static int MultiplyAndClamp(int baseline, float multiplier, int min, int max)
    {
        multiplier = ClampFinite(multiplier, 0f, 2f);
        var requested = (int)Math.Round(baseline * multiplier, MidpointRounding.AwayFromZero);
        return Math.Clamp(requested, min, max);
    }
}
