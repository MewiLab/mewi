using System.Linq;
using UnityEngine;

public class CreatureBlackBoard : MonoBehaviour
{
    string _currentIntent = "wander";
    float _hunger = 0.1f; // just for the gameplay state of the agent
    
    // Why need recent events?, just a rollingback feed for LLM
    public System.Collections.Generic.Queue<string> recent_events
        = new System.Collections.Generic.Queue<string>();

    
    public void SetCurrentIntent(string new_intent)
    {
        _currentIntent = new_intent; // need deep copy?
    }

    public float GetCurrentHunger()
    {
        return _hunger;
    }

        public void SetCurrentHunger(float new_hunger)
    {
        _hunger = new_hunger;
    }

    public string GetCurrentIntent()
    {
        return _currentIntent;
    }

    
    public void LogEvent(string e)
    {
        recent_events.Enqueue(e);
        if (recent_events.Count > 10) // keep at most 10 recent events for short memory in this version
        {
            recent_events.Dequeue();
        }
    }

}
