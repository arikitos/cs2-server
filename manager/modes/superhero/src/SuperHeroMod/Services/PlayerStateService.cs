using SuperHeroMod.Core;

namespace SuperHeroMod.Services;

public sealed class PlayerStateService
{
    private readonly Dictionary<uint, PlayerHeroState> _states = [];
    public PlayerHeroState Get(uint playerIndex)
    {
        if (!_states.TryGetValue(playerIndex, out var state))
        {
            state = new PlayerHeroState();
            _states[playerIndex] = state;
        }
        return state;
    }
    public bool TryGet(uint playerIndex, out PlayerHeroState state) => _states.TryGetValue(playerIndex, out state!);
    public void Remove(uint playerIndex) => _states.Remove(playerIndex);
    public void Clear() => _states.Clear();
}
