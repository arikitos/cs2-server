using RetakesAllocatorCore.Config;

namespace RetakesAllocatorCore.Managers;

public class RoundTypeManager
{
    #region Instance management

    private static RoundTypeManager? _instance;

    public static RoundTypeManager Instance => _instance ??= new RoundTypeManager();

    #endregion

    private string? _map;

    private RoundType? _nextRoundTypeOverride;
    private RoundType? _currentRoundType;

    private RoundTypeSelectionOption _roundTypeSelection;
    private readonly List<RoundType> _roundsOrder = new();
    private int _roundTypeManualOrderingPosition;

    private int _loadoutSequenceRoundNumber;

    private RoundTypeManager()
    {
        Initialize();
    }

    public void Initialize()
    {
        _nextRoundTypeOverride = null;
        _currentRoundType = null;
        _roundTypeSelection = Configs.GetConfigData().RoundTypeSelection;

        _roundsOrder.Clear();
        switch (_roundTypeSelection)
        {
            case RoundTypeSelectionOption.RandomFixedCounts:
                foreach (var (roundType, fixedCount) in Configs.GetConfigData().RoundTypeRandomFixedCounts)
                {
                    for (var i = 0; i < fixedCount; i++)
                    {
                        _roundsOrder.Add(roundType);
                    }
                }
                Utils.Shuffle(_roundsOrder);
                break;
            case RoundTypeSelectionOption.ManualOrdering:
                foreach (var item in Configs.GetConfigData().RoundTypeManualOrdering)
                {
                    for (var i = 0; i < item.Count; i++)
                    {
                        _roundsOrder.Add(item.Type);
                    }
                }
                break;
        }
        _roundTypeManualOrderingPosition = 0;
        _loadoutSequenceRoundNumber = 1;
    }

    public void SetMap(string map)
    {
        _map = map;
    }

    public string? Map => _map;

    public RoundType GetNextRoundType()
    {
        if (_nextRoundTypeOverride is not null)
        {
            return _nextRoundTypeOverride.Value;
        }

        switch (_roundTypeSelection)
        {
            // Falls back to Random when LoadoutSequence is selected but RoundLoadoutSequence is
            // empty or invalid at runtime, preserving legacy behavior instead of crashing.
            case RoundTypeSelectionOption.Random:
            case RoundTypeSelectionOption.LoadoutSequence:
                return GetRandomRoundType();
            case RoundTypeSelectionOption.ManualOrdering:
            case RoundTypeSelectionOption.RandomFixedCounts:
                return GetNextRoundTypeInOrder();
        }

        throw new Exception("No round type selection type was found.");
    }

    private RoundType GetNextRoundTypeInOrder()
    {
        if (_roundTypeManualOrderingPosition >= _roundsOrder.Count)
        {
            _roundTypeManualOrderingPosition = 0;
        }
        return _roundsOrder[_roundTypeManualOrderingPosition++];
    }

    private RoundType GetRandomRoundType()
    {
        var randomValue = new Random().NextDouble();

        var pistolPercentage = Configs.GetConfigData().GetRoundTypePercentage(RoundType.Pistol);

        if (randomValue < pistolPercentage)
        {
            return RoundType.Pistol;
        }

        if (randomValue < Configs.GetConfigData().GetRoundTypePercentage(RoundType.HalfBuy) + pistolPercentage)
        {
            return RoundType.HalfBuy;
        }

        return RoundType.FullBuy;
    }

    public void SetNextRoundTypeOverride(RoundType? nextRoundType)
    {
        _nextRoundTypeOverride = nextRoundType;
    }

    public RoundType? GetCurrentRoundType()
    {
        return _currentRoundType;
    }

    public void SetCurrentRoundType(RoundType? currentRoundType)
    {
        _currentRoundType = currentRoundType;
    }

    public bool IsLoadoutSequenceActive()
    {
        return _roundTypeSelection == RoundTypeSelectionOption.LoadoutSequence
               && Configs.GetConfigData().RoundLoadoutSequence.Count > 0;
    }

    public int GetCurrentLoadoutSequenceRoundNumber()
    {
        return _loadoutSequenceRoundNumber;
    }

    public void AdvanceLoadoutSequenceRound()
    {
        _loadoutSequenceRoundNumber++;
    }

    public RoundLoadoutStage GetCurrentLoadoutStage()
    {
        var roundNumber = _loadoutSequenceRoundNumber;
        var stage = Configs.GetConfigData().RoundLoadoutSequence
            .FirstOrDefault(s => s.ContainsRound(roundNumber));

        if (stage is not null)
        {
            return stage;
        }

        // Round number is past the last bounded stage and no open-ended stage exists;
        // fall back to the last configured stage (config validation prevents gaps for well-formed sequences).
        return Configs.GetConfigData().RoundLoadoutSequence
            .OrderBy(s => s.FromRound)
            .Last();
    }
}
